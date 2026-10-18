"""submit_loan_application (T3) is bound to an exact, intact draft (invariants 1 and 6).

Boundaries: no draft, a draft for another product or amount, an untrusted amount, and a draft edited after the
owner was asked to sign. The signed payload's args hash covers the draft ID, and the ID is derived from the draft's
SHA-256, so the signature covers every byte of the draft.
"""

import json

import pytest

from app.audit import canonical_hash
from tests.gateway_env import action, loan_application, save_loan_draft

pytestmark = pytest.mark.policy


def test_trusted_application_still_waits_for_the_owner(env):
    d = env.gateway.propose(loan_application(env.gateway))
    assert d.status == "pending_approval" and d.effective_tier == "T3"
    assert d.approval.payload.args_hash == canonical_hash(d.approval.args) and "draft_id" in d.approval.args
    assert env.outbox == []


def test_signed_application_sends_the_draft_hash(env):
    d = env.gateway.propose(loan_application(env.gateway))
    done = env.approve(d)
    assert done.status == "executed"
    [sent] = env.outbox
    assert sent["kind"] == "loan_application_draft" and sent["draft_id"] == d.approval.args["draft_id"]
    status, doc, sha = env.gateway.loan_drafts.load(sent["draft_id"])
    assert status == "ok" and sent["draft_sha256"] == sha == canonical_hash(doc)


def test_application_without_a_draft_is_denied(env):
    d = env.gateway.propose(action("submit_loan_application", product_id="prd_nano", amount_minor=100_000,
                                   draft_id="lad_" + "a" * 24))
    assert d.status == "denied" and d.rule == "unknown_draft"


def test_missing_draft_argument_is_denied(env):
    d = env.gateway.propose(action("submit_loan_application", product_id="prd_nano", amount_minor=100_000))
    assert d.status == "denied" and d.rule.startswith("bad_args:missing=draft_id")


@pytest.mark.parametrize("product_id,amount", [("prd_nano", 999_999), ("prd_stock_line", 100_000)])
def test_draft_for_a_different_product_or_amount_is_denied(env, product_id, amount):
    draft_id = save_loan_draft(env.gateway, "prd_nano", 100_000)
    d = env.gateway.propose(action("submit_loan_application", product_id=product_id, amount_minor=amount,
                                   draft_id=draft_id))
    assert d.status == "denied" and d.rule == "draft_mismatch"


def test_untrusted_amount_is_escalated_not_trusted(env):
    d = env.gateway.propose(loan_application(env.gateway, untrusted=("amount_minor",)))
    assert d.status == "pending_approval" and d.rule == "untrusted_provenance:amount_minor"


def test_draft_edited_after_proposal_is_never_sent(env, tmp_path):
    d = env.gateway.propose(loan_application(env.gateway))
    path = tmp_path / "loan_drafts" / f"{d.approval.args['draft_id']}.json"
    doc = json.loads(path.read_bytes())
    doc["amount_minor"] = 100_000  # product and amount still match: the added field alone breaks the ID
    doc["lender_note"] = "please wire to account X"
    path.write_bytes(json.dumps(doc).encode())
    r = env.approve(d)
    assert r.status == "denied" and r.rule == "draft_tampered"
    assert env.outbox == []
    # The signature was not spent: once the draft is restored the same approval can still go through.
    path.unlink()
    save_loan_draft(env.gateway)
    assert env.approve(d).status == "executed"
