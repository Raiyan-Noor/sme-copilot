"""Payments tab end to end over HTTP: connect SandboxPay through its consent screen, pay a supplier invoice with one
signature, watch it settle by signed webhook into the ledger (cash and buffer days move), and the side paths: a bill
covered by a standing mandate, an added payee, cancel, a missed webhook, a failed payment, history filters."""

import json

import pytest

from tests.agent_env import build_template, copy_data_dir
from tests.payments_env import MAYA, TOKEN_KEY, payments_env

INVOICE = "item:MCS-SCH-0005"  # FreshLine invoice FL-26-0049, from the business's own bookkeeping records
BILL = "item:MCS-SCH-0006"  # LinkFast internet bill, due tomorrow


@pytest.fixture(scope="module")
def template(tmp_path_factory):
    return build_template(tmp_path_factory.mktemp("payments-api"))


@pytest.fixture
def make(template, tmp_path):
    data_dir, seed_dir = template
    counter = iter(range(100))

    def build(**kwargs):
        return payments_env(copy_data_dir(data_dir, tmp_path / f"tenants-{next(counter)}"), seed_dir, **kwargs)

    return build


def _cash(env) -> tuple[int, float]:
    c = env.app.get(env.url("/cash")).json()
    return c["balance"]["value"], c["buffer_days"]["value"]


def test_connect_shows_consent_and_stores_only_an_encrypted_token(make):
    env = make()
    assert env.overview()["connection"]["state"] == "not_connected"
    out = env.connect(per_payment=2000, daily=5000)  # the owner lowers both caps on the provider's screen
    assert out["status"] == 200 and "connected" in out["page"]
    page = env.provider_client.get("/authorize", params=out["query"]).text
    assert "Send payments" in page and "cannot" in page.lower()
    status = env.overview()["connection"]
    assert status["state"] == "connected" and status["scopes"] == ["payments.send", "payments.read"]
    assert status["per_payment_cap_minor"] == 200_000 and status["daily_cap_minor"] == 500_000
    assert status["spent_today_minor"] == 0 and status["provider_reachable"] is True
    # The bearer token and webhook secret exist only encrypted: never in an API response or the audit log.
    raw = (env.rt.data_dir / MAYA / "sandboxpay.sqlite").read_bytes()
    assert b"spt_" not in raw and b"whsec_" not in raw
    assert "spt_" not in json.dumps(env.overview()) and "spt_" not in env.rt.audit.path.read_text(encoding="utf-8")
    assert "payments.provider_connected" in env.audit_kinds()


def test_consent_denied_connects_nothing(make):
    env = make()
    out = env.connect(decision="deny")
    assert out["status"] == 400
    assert env.overview()["connection"]["state"] == "not_connected"
    assert "payments.connect_failed" in env.audit_kinds()


def test_callback_with_an_unknown_state_is_refused(make):
    env = make()
    r = env.app.get("/payments/sandboxpay/callback", params={"state": "forged", "code": "x"})
    assert r.status_code == 400 and env.overview()["connection"]["state"] == "not_connected"


def test_invoice_paid_with_one_signature_settles_into_the_ledger(make):
    env = make()
    env.connect()
    balance0, buffer0 = _cash(env)
    req = env.create(source=INVOICE)
    assert req["status"] == "awaiting_approval" and req["tool"] == "pay_invoice" and req["approval_id"]
    assert req["account_last4"] == "0937" and req["amount_minor"] == 128_718
    view = env.app.get(env.url(f"/gateway/approvals/{req['approval_id']}")).json()
    assert view["args"] == {"payee_id": "sup_fresh", "account_token": req["account_token"],
                            "amount_minor": 128_718, "reference": "FL-26-0049", "request_id": req["id"]}

    decision = env.approve(req)
    assert decision["status"] == "executed"
    sent = env.get(req["id"])
    assert sent["status"] == "sent" and sent["provider_payment_id"].startswith("pmt_")
    assert [e["status"] for e in sent["events"]] == ["proposed", "awaiting_approval", "approved", "sent"]
    assert env.ledger_rows(req["id"]) == []  # nothing in the ledger until the provider settles

    env.settle()
    assert env.webhooks and env.webhooks[-1][0] == 200
    done = env.get(req["id"])
    assert done["status"] == "settled" and done["receipt_sha256"]
    [row] = env.ledger_rows(req["id"])
    assert row["amount_minor"] == -128_718 and row["category"] == "fresh_produce"
    balance1, buffer1 = _cash(env)
    assert balance1 == balance0 - 128_718 and buffer1 < buffer0
    with env.rt.business(MAYA) as conn:
        assert conn.execute("SELECT status FROM scheduled_items WHERE id = 'MCS-SCH-0005'").fetchone()[0] == "paid"
    assert INVOICE not in [s["key"] for s in env.overview()["suggestions"]]
    # The Transactions tab shows it as a payment; the receipt re-hashes to what was logged for anchoring.
    tx = env.app.get(env.url(f"/transactions/txn_{req['id']}")).json()
    assert tx["source"] == "payment" and tx["status"] == "settled"
    receipt = env.app.get(env.url(f"/payments/requests/{req['id']}/receipt")).json()
    from app.audit.canonical import canonical_hash
    assert canonical_hash(receipt["document"]) == receipt["receipt_sha256"] == done["receipt_sha256"]
    settled = [e for e in env.rt.audit.entries() if e.kind == "payments.settled"]
    assert settled[-1].data["receipt_sha256"] == done["receipt_sha256"]
    assert env.overview()["connection"]["spent_today_minor"] == 128_718


def test_settled_receipt_joins_an_anchoring_batch(make):
    env = make()
    env.connect()
    req = env.create(source=INVOICE)
    env.approve(req)
    env.settle()
    env.rt.anchors.request("test", manual=True)
    check = env.app.get(env.url(f"/payments/requests/{req['id']}/onchain")).json()
    assert check["kind"] == "payment" and check["hash"] == env.get(req["id"])["receipt_sha256"]
    assert check["status"] != "not_found"


def test_bill_inside_a_signed_limit_runs_without_asking(make):
    env = make()
    env.connect()
    env.grant_bills(10_000, ["pay_linkfast"])
    [bill] = [s for s in env.overview()["suggestions"] if s["key"] == BILL]
    assert bill["covered_by_mandate"] is True
    req = env.create(source=BILL)
    assert req["status"] == "sent" and req["tool"] == "pay_recurring_bill" and req["approval_id"] is None
    env.settle()
    assert env.get(req["id"])["status"] == "settled" and env.ledger_rows(req["id"])[0]["amount_minor"] == -6_500


def test_bill_above_the_signed_limit_waits_for_a_signature(make):
    env = make()
    env.connect()
    env.grant_bills(5_000, ["pay_linkfast"])  # the bill is 6500
    req = env.create(source=BILL)
    assert req["status"] == "awaiting_approval" and req["tool"] == "pay_invoice"


def test_new_payee_needs_extra_confirmation_then_a_signature(make):
    env = make()
    env.connect()
    url = env.url("/payments/payees")
    base = {"name": "Corner Signs Co", "account_number": "4410 2200 9183"}
    assert env.app.post(url, json={**base, "confirm_account_number": "4410 2200 9184", "confirmed": True}
                        ).status_code == 422
    assert env.app.post(url, json={**base, "confirm_account_number": "4410 2200 9183"}).status_code == 422
    r = env.app.post(url, json={**base, "confirm_account_number": "441022009183", "confirmed": True})
    assert r.status_code == 200, r.text
    payee = r.json()
    assert payee["verified"] is False and payee["account_last4"] == "9183" and "4410" not in json.dumps(payee)
    req = env.create(payee_id=payee["id"], amount_minor=12_000, reason="New shop sign")
    assert req["status"] == "awaiting_approval" and req["source_kind"] == "manual"
    env.approve(req)
    env.settle()
    assert env.get(req["id"])["status"] == "settled"
    assert "payments.payee_added" in env.audit_kinds()


def test_manual_request_to_an_unknown_payee_is_refused(make):
    env = make()
    r = env.app.post(env.url("/payments/requests"), json={"payee_id": "pay_nobody", "amount_minor": 100})
    assert r.status_code == 422


def test_cancel_retires_the_approval(make):
    env = make()
    env.connect()
    req = env.create(source=INVOICE)
    r = env.app.post(env.url(f"/payments/requests/{req['id']}/cancel"))
    assert r.status_code == 200 and r.json()["status"] == "cancelled"
    decision = env.approve(req)
    assert decision["status"] == "denied"
    assert env.provider.settle_due(force=True) == []


def test_missed_webhook_is_recovered_by_a_status_check(make):
    env = make()
    env.connect()
    env.drop_webhooks = True
    req = env.create(source=INVOICE)
    env.approve(req)
    env.settle()
    assert env.get(req["id"])["status"] == "sent"
    r = env.app.post(env.url(f"/payments/requests/{req['id']}/refresh"))
    assert r.json()["status"] == "settled" and len(env.ledger_rows(req["id"])) == 1


def test_failed_settlement_leaves_the_ledger_alone(make):
    env = make(fail_accounts=())
    env.connect()
    req = env.create(source=INVOICE)
    env.provider.config.fail_accounts = frozenset({req["account_token"]})
    env.approve(req)
    env.settle()
    done = env.get(req["id"])
    assert done["status"] == "failed" and done["rule"] == "account_closed"
    assert env.ledger_rows(req["id"]) == []
    assert "payments.failed" in env.audit_kinds()


def test_without_a_connected_provider_nothing_is_sent(make):
    env = make()
    req = env.create(source=INVOICE)
    env.approve(req)
    done = env.get(req["id"])
    assert done["status"] == "failed" and done["rule"] == "not_connected" and env.ledger_rows(req["id"]) == []


def test_history_filters_by_status_and_payee(make):
    env = make()
    env.connect()
    a = env.create(source=INVOICE)
    b = env.create(source=BILL)
    env.app.post(env.url(f"/payments/requests/{b['id']}/cancel"))
    assert [r["id"] for r in env.overview(status="cancelled")["requests"]] == [b["id"]]
    assert [r["id"] for r in env.overview(payee_id="sup_fresh")["requests"]] == [a["id"]]


def test_payment_status_is_published_live(make):
    env = make()
    env.connect()
    seq = env.rt.inbox_events.latest()
    req = env.create(source=INVOICE)
    env.approve(req)
    env.settle()
    statuses = [e.payment["status"] for e in env.rt.inbox_events.since(MAYA, seq) if e.kind == "payment"]
    assert statuses == ["awaiting_approval", "sent", "settled"]


def test_token_key_is_required_to_connect(make):
    env = make(sandboxpay_token_key="", gmail_token_key="")
    r = env.app.post(env.url("/connections/payments/connect"), json={})
    assert r.status_code == 422 and "SANDBOXPAY_TOKEN_KEY" in r.json()["detail"]
    assert env.overview()["connection"]["state"] == "not_configured"
    assert TOKEN_KEY  # the harness's key is what makes every other test connect
