"""Signed mandates (invariant 6): signature, signer, args binding, expiry, nonce replay, out-of-band call, and the
canonical-JSON hash stored for anchoring."""

from datetime import timedelta

import pytest

from app.audit import canonical_hash
from app.gateway import SignedPayload, StandingTerms, load_policy
from tests.gateway_env import Owner, action, bill, loan_application

pytestmark = pytest.mark.policy

TTL = load_policy().approval_ttl_days
MAX_DAYS = load_policy().standing_mandate_max_days
BILL_CAP = load_policy().t2["pay_recurring_bill"].max_amount_minor


def loan(env):
    return env.gateway.propose(loan_application(env.gateway))


# T3 approvals

def test_signed_approval_executes_once(env):
    d = loan(env)
    done = env.approve(d)
    assert done.status == "executed" and done.mandate_id is not None
    assert env.outbox[0]["kind"] == "loan_application_draft"


def test_replayed_approval_signature_denied(env):
    d = loan(env)
    sig = env.owner.sign(d.approval.payload)
    assert env.gateway.approve(d.approval.approval_id, sig, env.owner.public_key).status == "executed"
    again = env.gateway.approve(d.approval.approval_id, sig, env.owner.public_key)
    assert again.status == "denied" and again.rule == "replayed_nonce"
    assert len(env.outbox) == 1


def test_nonce_consumed_by_standing_mandate_cannot_be_reused_in_another(env):
    terms = StandingTerms(max_amount_minor=BILL_CAP, allowlist=("pay_citygrid",))
    payload = env.standing_payload("pay_recurring_bill", terms, nonce="shared-nonce-0000001")
    sig = env.owner.sign(payload)
    assert env.gateway.register_standing_mandate(payload, terms, sig, env.owner.public_key).accepted
    replay = env.gateway.register_standing_mandate(payload, terms, sig, env.owner.public_key)
    assert not replay.accepted and replay.rule == "replayed_nonce"


def test_approval_from_unenrolled_key_denied(env):
    d = loan(env)
    stranger = Owner(b"\x02" * 32)
    r = env.approve(d, owner=stranger)
    assert r.status == "denied" and r.rule == "unknown_signer"
    assert env.outbox == []


def test_tampered_signature_denied(env):
    d = loan(env)
    sig = bytearray.fromhex(env.owner.sign(d.approval.payload))
    sig[0] ^= 1
    r = env.gateway.approve(d.approval.approval_id, sig.hex(), env.owner.public_key)
    assert r.status == "denied" and r.rule == "bad_signature"


@pytest.mark.parametrize("bad_sig", ["", "zz", "00" * 64])
def test_malformed_signature_denied(env, bad_sig):
    d = loan(env)
    r = env.gateway.approve(d.approval.approval_id, bad_sig, env.owner.public_key)
    assert r.status == "denied" and r.rule == "bad_signature"


def test_signature_over_different_args_does_not_approve(env):
    """The owner signed a smaller loan; that signature cannot approve the pending larger one."""
    d = loan(env)
    p = d.approval.payload
    other = SignedPayload(action=p.action, args_hash=canonical_hash({"amount_minor": 1, "draft_id": "lad_x", "product_id": "prd_nano"}),
                          nonce=p.nonce, expiry=p.expiry)
    r = env.gateway.approve(d.approval.approval_id, env.owner.sign(other), env.owner.public_key)
    assert r.status == "denied" and r.rule == "bad_signature"


def test_signature_for_one_approval_cannot_approve_another(env):
    a, b = loan(env), loan(env)
    r = env.gateway.approve(b.approval.approval_id, env.owner.sign(a.approval.payload), env.owner.public_key)
    assert r.status == "denied" and r.rule == "bad_signature"


def test_approval_valid_through_expiry_day(env):
    d = loan(env)
    env.clock.advance(TTL)
    assert env.approve(d).status == "executed"


def test_expired_approval_denied_and_nonce_not_burned(env):
    d = loan(env)
    env.clock.advance(TTL + 1)
    r = env.approve(d)
    assert r.status == "denied" and r.rule == "expired"
    assert not env.gateway.store.nonce_used(d.approval.payload.nonce)
    assert env.outbox == []


def test_unknown_approval_denied(env):
    r = env.gateway.approve("apr_does_not_exist", "00" * 64, env.owner.public_key)
    assert r.status == "denied" and r.rule == "unknown_approval"


def test_payee_change_needs_out_of_band_call(env):
    d = env.gateway.propose(action("change_payee_details", payee_id="pay_citygrid", account_token="acct_new"))
    assert d.approval.requires_out_of_band_call_script
    r = env.approve(d)
    assert r.status == "denied" and r.rule == "out_of_band_call_required"
    assert env.approve(d, out_of_band_confirmed=True).status == "executed"


def test_approval_payload_binds_exact_args_and_ttl(env):
    d = loan(env)
    p = d.approval.payload
    assert p.args_hash == canonical_hash({"amount_minor": 100_000, "draft_id": d.approval.args["draft_id"],
                                          "product_id": "prd_nano"})
    assert p.expiry == env.clock.today() + timedelta(days=TTL)
    assert len(p.nonce) == 32


# Standing mandates

def _register(env, terms, action_name="pay_recurring_bill", days=30, signer=None, payload=None):
    signer = signer or env.owner
    payload = payload or env.standing_payload(action_name, terms, days)
    return env.gateway.register_standing_mandate(payload, terms, signer.sign(payload), signer.public_key)


def test_standing_mandate_cannot_raise_policy_cap(env):
    r = _register(env, StandingTerms(max_amount_minor=BILL_CAP + 1, allowlist=("pay_citygrid",)))
    assert not r.accepted and r.rule == "raises_policy_cap"


@pytest.mark.parametrize("tool", ["submit_loan_application", "get_passport", "fire_employee"])
def test_standing_mandate_only_for_t2_tools(env, tool):
    r = _register(env, StandingTerms(max_amount_minor=1, allowlist=("x",)), action_name=tool)
    assert not r.accepted and r.rule == "not_a_t2_tool"


def test_standing_mandate_terms_must_match_signed_hash(env):
    signed_terms = StandingTerms(max_amount_minor=1_000, allowlist=("pay_citygrid",))
    payload = env.standing_payload("pay_recurring_bill", signed_terms)
    swapped = StandingTerms(max_amount_minor=BILL_CAP, allowlist=("pay_citygrid", "pay_attacker"))
    r = env.gateway.register_standing_mandate(payload, swapped, env.owner.sign(payload), env.owner.public_key)
    assert not r.accepted and r.rule == "args_hash_mismatch"


def test_standing_mandate_from_unenrolled_key_rejected(env):
    r = _register(env, StandingTerms(max_amount_minor=1, allowlist=("x",)), signer=Owner(b"\x03" * 32))
    assert not r.accepted and r.rule == "unknown_signer"


def test_standing_mandate_already_expired_rejected(env):
    r = _register(env, StandingTerms(max_amount_minor=1, allowlist=("x",)), days=-1)
    assert not r.accepted and r.rule == "expired"


def test_standing_mandate_length_capped(env):
    terms = StandingTerms(max_amount_minor=1, allowlist=("x",))
    assert _register(env, terms, days=MAX_DAYS).accepted
    r = _register(env, terms, days=MAX_DAYS + 1)
    assert not r.accepted and r.rule == "mandate_too_long"


def test_rejected_mandates_are_logged(env):
    _register(env, StandingTerms(max_amount_minor=BILL_CAP + 1, allowlist=("x",)))
    rejected = [e.data for e in env.audit.entries() if e.kind == "gateway.mandate_rejected"]
    assert rejected and rejected[0]["rule"] == "raises_policy_cap"


# Stored hashes for anchoring

def test_every_signed_mandate_stored_with_canonical_hash(env):
    standing = env.grant("pay_recurring_bill", BILL_CAP, ("pay_citygrid",))
    env.gateway.propose(bill())
    approved = env.approve(loan(env))
    stored = env.gateway.store.mandates_since(0)
    assert [m.kind for m in stored] == ["standing", "approval"]
    assert stored[1].id == approved.mandate_id
    for m in stored:
        assert m.record_hash == canonical_hash(m.document())
    assert stored[0].record_hash == standing.record_hash
    assert [m.id for m in env.gateway.store.mandates_since(stored[0].id)] == [stored[1].id]
    logged = [e.data["record_hash"] for e in env.audit.entries() if e.kind == "gateway.mandate_stored"]
    assert logged == [m.record_hash for m in stored]


def test_rejected_or_replayed_signatures_store_no_mandate(env):
    d = loan(env)
    sig = env.owner.sign(d.approval.payload)
    env.gateway.approve(d.approval.approval_id, sig, env.owner.public_key)
    env.gateway.approve(d.approval.approval_id, sig, env.owner.public_key)
    _register(env, StandingTerms(max_amount_minor=BILL_CAP + 1, allowlist=("x",)))
    assert len(env.gateway.store.mandates_since(0)) == 1


def test_state_survives_restart(env, tmp_path):
    """Nonces, mandates and frequency history are on disk, so a restart cannot be used to replay."""
    from app.gateway import Gateway

    d = loan(env)
    sig = env.owner.sign(d.approval.payload)
    assert env.gateway.approve(d.approval.approval_id, sig, env.owner.public_key).status == "executed"
    restarted = Gateway.for_tenant(tmp_path, env.audit, env.clock)
    r = restarted.approve(d.approval.approval_id, sig, env.owner.public_key)
    assert r.status == "denied" and r.rule == "replayed_nonce"
    assert len(restarted.store.mandates_since(0)) == 1
    assert env.audit.verify().ok
