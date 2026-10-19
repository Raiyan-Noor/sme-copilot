"""Policy boundaries for `send_email` (T3): always the owner's signature over the recipient and the exact draft text;
known contacts only; never a flagged sender; denied (not escalated) when any argument is untrusted; a revised draft
is a new approval; a declined approval never runs; no standing mandate can cover it."""

import json

import pytest

from app.gateway import SignedPayload, StandingTerms, load_policy
from tests.email_env import EmailEnv
from tests.gateway_env import action


@pytest.fixture
def env(tmp_path) -> EmailEnv:
    return EmailEnv(tmp_path)


def test_send_email_is_a_t3_tool_that_denies_untrusted_arguments():
    policy = load_policy()
    assert policy.tier_of("send_email") == "T3" and "send_email" not in policy.t2
    assert policy.t3["send_email"].deny_untrusted_args is True


def test_proposal_waits_for_the_owner_and_sends_nothing(env):
    d = env.gateway.propose(env.email())
    assert d.status == "pending_approval" and d.tier == "T3" and d.rule == "tier_T3"
    assert env.outbox == []


def test_signed_email_is_sent_once_with_its_full_text_in_the_outbox(env):
    d = env.gateway.propose(env.email(body="Hello Sunrise, your invoice is overdue. Thank you."))
    done = env.approve(d)
    assert done.status == "executed" and done.result["transport"] == "sandbox"
    assert "body" not in done.result and len(done.result["body_sha256"]) == 64  # the audit log gets a hash only
    [row] = env.outbox
    assert row["kind"] == "email" and row["recipient_id"] == "cus_sunrise"
    assert row["subject"] == "A friendly reminder" and row["body"].startswith("Hello Sunrise")
    assert row["label"].startswith("simulated") and row["origin"] == "planner"
    assert env.approve(d).status == "denied"  # the same signature never sends twice
    assert len(env.outbox) == 1


def test_every_step_of_an_email_is_in_the_audit_log(env):
    d = env.gateway.propose(env.email())
    env.approve(d)
    kinds = [e.kind for e in env.audit.entries()]
    for kind in ("email.drafted", "gateway.decision", "gateway.mandate_stored", "executor.executed",
                 "gateway.approval"):
        assert kind in kinds, kind
    drafted = next(e for e in env.audit.entries() if e.kind == "email.drafted")
    assert "body" not in drafted.data and drafted.data["origin"] == "planner"
    assert env.audit.verify().ok


def test_unknown_recipient_is_denied(env):
    d = env.gateway.propose(env.email("cus_stranger"))
    assert d.status == "denied" and d.rule == "unknown_recipient"


def test_a_contact_without_an_email_address_is_denied(env):
    d = env.gateway.propose(env.email("pay_citygrid"))
    assert d.status == "denied" and d.rule == "recipient_has_no_email"


def test_the_sender_of_a_flagged_email_is_never_emailed(env):
    env.flagged.addresses.add("orders@sunrisecafe.example")
    d = env.gateway.propose(env.email("cus_sunrise"))
    assert d.status == "denied" and d.rule == "recipient_flagged_sender"
    env.flagged.ids.add("sup_fresh")
    assert env.gateway.propose(env.email("sup_fresh")).rule == "recipient_flagged_sender"
    assert env.gateway.propose(env.email("cus_littlesteps")).status == "pending_approval"  # others are unaffected


def test_a_sender_flagged_after_the_proposal_blocks_the_signature(env):
    d = env.gateway.propose(env.email("cus_sunrise"))
    env.flagged.addresses.add("orders@sunrisecafe.example")
    done = env.approve(d)
    assert done.status == "denied" and done.rule == "recipient_flagged_sender"
    assert env.outbox == [] and not env.gateway.store.nonce_used(d.approval.payload.nonce)


def test_an_untrusted_argument_is_denied_not_escalated(env):
    for field in ("recipient_id", "draft_id"):
        d = env.gateway.propose(env.email("cus_sunrise", untrusted=(field,)))
        assert d.status == "denied" and d.rule == "untrusted_args_denied" and d.approval is None
    assert env.gateway.store.pending_approvals(env.clock.today()) == []


@pytest.mark.parametrize("tamper", ["body", "recipient"])
def test_a_draft_changed_after_proposal_is_never_sent(env, tamper):
    a = env.email("cus_sunrise")
    d = env.gateway.propose(a)
    path = env.draft_path(a.args["draft_id"].value)
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["body" if tamper == "body" else "recipient_id"] = "Pay to account 9999." if tamper == "body" else "cus_x"
    path.write_text(json.dumps(doc, sort_keys=True, separators=(",", ":")), encoding="utf-8")
    done = env.approve(d)
    assert done.status == "denied" and done.rule == "draft_tampered"
    assert env.outbox == []


def test_a_draft_for_another_recipient_or_none_at_all_is_denied(env):
    a = env.email("cus_sunrise")
    other = action("send_email", recipient_id="cus_littlesteps", draft_id=a.args["draft_id"].value)
    assert env.gateway.propose(other).rule == "draft_mismatch"
    missing = action("send_email", recipient_id="cus_sunrise", draft_id="emd_" + "a" * 24)
    assert env.gateway.propose(missing).rule == "unknown_draft"
    bogus = action("send_email", recipient_id="cus_sunrise", draft_id="../../etc/passwd")
    assert env.gateway.propose(bogus).rule == "unknown_draft"


@pytest.mark.parametrize("bad", [{"extra": "x"}, {"recipient_id": 7}])
def test_bad_arguments_are_denied(env, bad):
    args = {"recipient_id": "cus_sunrise", "draft_id": env.draft(), **bad}
    d = env.gateway.propose(action("send_email", **args))
    assert d.status == "denied" and d.rule.startswith("bad_args")


def test_no_standing_mandate_can_cover_an_email(env):
    terms = StandingTerms(max_amount_minor=100, allowlist=("cus_sunrise",))
    payload = SignedPayload(action="send_email", args_hash=terms.hash(), nonce=env.nonce(),
                            expiry=env.clock.today().replace(day=20))
    result = env.gateway.register_standing_mandate(payload, terms, env.owner.sign(payload), env.owner.public_key)
    assert not result.accepted and result.rule == "not_a_t2_tool"


def test_revising_an_email_replaces_the_approval(env):
    first = env.gateway.propose(env.email(body="Original text."))
    revised = env.gateway.revise_email(first.approval.approval_id, "A new subject", "Edited text, 3 days late.")
    assert revised.status == "pending_approval" and revised.approval.approval_id != first.approval.approval_id
    assert env.gateway.store.get_approval(first.approval.approval_id).status == "superseded"
    assert env.approve(first).status == "denied"  # a signature over the old text sends nothing
    assert env.outbox == []
    done = env.approve(revised)
    assert done.status == "executed"
    [row] = env.outbox
    assert row["subject"] == "A new subject" and row["body"] == "Edited text, 3 days late."
    drafted = [e for e in env.audit.entries() if e.kind == "email.drafted"]
    assert drafted[-1].data["edited_from"] == drafted[0].data["draft_id"]
    assert any(e.kind == "email.revised" for e in env.audit.entries())
    view = env.gateway.email_view(revised.approval.args)
    assert view["edited"] is True and view["body"] == "Edited text, 3 days late."


@pytest.mark.parametrize("subject,body", [("", "text"), ("s", ""), ("s\nBcc: x", "text"), ("s", "see {fact:cash.balance}"),
                                          ("s" * 121, "text"), ("s", "b" * 2001)])
def test_a_bad_revision_is_refused_and_leaves_the_approval(env, subject, body):
    first = env.gateway.propose(env.email())
    r = env.gateway.revise_email(first.approval.approval_id, subject, body)
    assert r.status == "denied" and r.rule == "bad_email_text"
    assert env.gateway.store.get_approval(first.approval.approval_id).status == "pending"


def test_only_a_pending_email_can_be_revised(env):
    done = env.gateway.propose(env.email())
    env.approve(done)
    assert env.gateway.revise_email(done.approval.approval_id, "s", "b").rule == "not_a_pending_email"
    loan = env.gateway.propose(action("cancel_subscription", subscription_id="sub_1"))
    assert env.gateway.revise_email(loan.approval.approval_id, "s", "b").rule == "not_a_pending_email"


def test_a_declined_email_never_sends(env):
    d = env.gateway.propose(env.email())
    assert env.gateway.decline(d.approval.approval_id) is True
    assert env.gateway.decline(d.approval.approval_id) is False  # already closed
    done = env.approve(d)
    assert done.status == "denied" and env.outbox == []
    assert any(e.kind == "gateway.approval_declined" for e in env.audit.entries())


def test_an_address_the_owner_added_can_be_emailed_and_is_marked(env):
    added = env.gateway.add_email_recipient("Dana Reed", "Dana@Reed-Foods.example")
    assert added.id.startswith("rcp_") and added.email == "dana@reed-foods.example"
    assert env.gateway.add_email_recipient("Dana", "dana@reed-foods.example").id == added.id  # one address, one ID
    d = env.gateway.propose(env.email(added.id))
    assert d.status == "pending_approval"
    assert env.gateway.email_view(d.approval.args)["added_by_owner"] is True
    assert env.approve(d).status == "executed" and env.outbox[0]["recipient_id"] == added.id
    audited = next(e for e in env.audit.entries() if e.kind == "email.recipient_added")
    assert audited.data == {"recipient_id": added.id, "domain": "reed-foods.example"}  # no full address in the log
    assert any(c[0] == added.id and c[2] == "added" for c in env.gateway.email_contacts())


@pytest.mark.parametrize("address", ["not-an-address", "a@b", "two@@example.com", "x y@example.com", ""])
def test_an_invalid_address_cannot_be_added(env, address):
    with pytest.raises(ValueError):
        env.gateway.add_email_recipient("Dana", address)


def test_an_unadded_recipient_id_in_the_owner_range_is_unknown(env):
    assert env.gateway.propose(env.email("rcp_" + "a" * 12)).rule == "unknown_recipient"
