"""Red team: attacks on the payment path (P3). Each case records its attack ID for docs/results/redteam.json.

The approval binds payee + amount + account; one idempotency key is one payment; an amount from an email always needs
a signature; a flagged email cannot be paid before the call-script check; disconnecting revokes the token at the
provider; forged or replayed webhooks change nothing; and the provider enforces its own caps even when the app is
bypassed entirely.
"""

import json

import pytest

from app.gateway import load_policy
from app.services.payments import PaymentsService
from tests.agent_env import build_template, copy_data_dir
from tests.owner_api import approve, propose
from tests.payments_env import MAYA, payments_env

INVOICE = "item:MCS-SCH-0005"  # FreshLine FL-26-0049, 128718


@pytest.fixture(scope="module")
def template(tmp_path_factory):
    return build_template(tmp_path_factory.mktemp("payment-attacks"))


@pytest.fixture
def make(template, tmp_path):
    data_dir, seed_dir = template
    counter = iter(range(100))

    def build(**kwargs):
        return payments_env(copy_data_dir(data_dir, tmp_path / f"tenants-{next(counter)}"), seed_dir, **kwargs)

    return build


def _provider_payments(env) -> int:
    return env.provider._conn.execute("SELECT COUNT(*) FROM payments").fetchone()[0]


def test_account_changed_after_approval_is_refused(make, attack):
    attack("ATK-PAY-ACCOUNT-SWAP", "payee's account changed after the owner was asked to sign", "scripted")
    env = make()
    env.connect()
    req = env.create(source=INVOICE)
    # A (signed, call-confirmed) payee change lands before the owner signs the payment.
    change = propose(env.app, MAYA, "change_payee_details", payee_id="sup_fresh", account_token="acct_attacker")
    assert approve(env.app, MAYA, change["approval"]["approval_id"], env.enroll(),
                   out_of_band_confirmed=True)["status"] == "executed"
    decision = env.approve(req)
    assert decision["status"] == "denied" and decision["rule"] == "payee_account_changed"
    assert _provider_payments(env) == 0 and env.get(req["id"])["status"] == "awaiting_approval"
    attack.caught("gateway", decision["rule"])


def test_amount_tampered_after_approval_is_refused(make, attack):
    attack("ATK-PAY-TAMPER", "stored payment amount raised after the owner was asked to sign", "scripted")
    env = make()
    env.connect()
    req = env.create(source=INVOICE)
    gw = env.rt.gateway(MAYA)
    approval = gw.store.get_approval(req["approval_id"])
    tampered = {**approval.args, "amount_minor": 999_999}
    gw.store._conn.execute("UPDATE approvals SET args = ? WHERE id = ?",
                           (json.dumps(tampered, sort_keys=True), req["approval_id"]))
    decision = env.approve(req)
    assert decision["status"] == "denied"
    assert decision["rule"] in ("payment_request_mismatch", "args_hash_mismatch")
    assert _provider_payments(env) == 0
    attack.caught("gateway", decision["rule"])


def test_double_approval_and_retry_pay_once(make, attack):
    attack("ATK-PAY-DOUBLE", "double click, replayed signature and repeated webhook", "scripted")
    env = make()
    env.connect()
    req = env.create(source=INVOICE)
    first = env.approve(req)
    second = env.approve(req)  # the same signature again
    assert first["status"] == "executed" and second["status"] == "denied"
    env.settle()
    status, event = env.webhooks[-1]
    body = json.dumps(event, sort_keys=True).encode()
    from sandboxpay.provider import sign_body
    secret = env.rt.payments._cipher().decrypt(env.rt.payments.connection_store(MAYA).get().webhook_secret_enc)
    again = env.app.post(f"/payments/sandboxpay/webhook/{MAYA}", content=body,
                         headers={"X-SandboxPay-Signature": sign_body(secret, body)})
    assert again.json()["outcome"] == "duplicate"
    assert _provider_payments(env) == 1 and len(env.ledger_rows(req["id"])) == 1
    # The provider itself: the same idempotency key with a different body is refused, the same body is the same payment.
    token = env.rt.payments._token(MAYA)
    hdr = {"Authorization": f"Bearer {token}", "Idempotency-Key": req["id"]}
    same = {"payee_ref": "sup_fresh", "payee_name": "x", "account_token": req["account_token"],
            "amount_minor": 128_718, "currency": env.overview()["connection"]["currency"], "reference": "FL-26-0049"}
    assert env.provider_client.post("/v1/payments", json=same, headers=hdr).status_code == 200
    assert env.provider_client.post("/v1/payments", json={**same, "amount_minor": 1}, headers=hdr).status_code == 409
    assert _provider_payments(env) == 1
    attack.caught("gateway", second["rule"])


def test_email_amount_needs_a_signature_even_under_a_mandate(make, attack):
    attack("ATK-PAY-EMAIL-AMOUNT", "invoice amount from an email, payee inside a standing mandate", "scripted")
    env = make()
    env.connect()
    env.grant_bills(load_policy().t2["pay_recurring_bill"].max_amount_minor, ["pay_linkfast"])
    with env.rt.business(MAYA) as conn, conn:  # an accepted email invoice, as quarantine/feed.py writes it
        conn.execute("INSERT INTO scheduled_items (id, kind, category, due_date, amount_minor, status,"
                     " counterparty_id, reference, source) VALUES ('MBX-EM-099-1', 'payable', 'utilities',"
                     " '2026-10-21', 6500, 'open', 'pay_linkfast', 'LF-INV-77', 'mailbox_invoice')")
    [s] = [s for s in env.overview()["suggestions"] if s["key"] == "item:MBX-EM-099-1"]
    assert s["amount_untrusted"] is True and s["covered_by_mandate"] is False
    req = env.create(source="item:MBX-EM-099-1")
    assert req["status"] == "awaiting_approval" and req["email_id"] == "em-099"
    decision = [e for e in env.rt.audit.entries() if e.kind == "gateway.decision"][-1].data
    assert decision["untrusted_args"] == ["amount_minor"] and decision["status"] == "pending_approval"
    # Directly through the gateway too: the T2 tool with that untrusted amount is escalated, not run.
    direct = propose(env.app, MAYA, "pay_recurring_bill", untrusted=("amount_minor",), payee_id="pay_linkfast",
                     bill_id="MBX-EM-099-1", amount_minor=6500)
    assert direct["status"] == "pending_approval"
    assert _provider_payments(env) == 0
    attack.caught("gateway", decision["rule"] or "untrusted_provenance")


def test_flagged_email_cannot_be_paid_before_the_call(make, attack):
    attack("ATK-PAY-FLAGGED", "pay a Sentinel-flagged (bank-detail-change) invoice email", "scripted")
    env = make()
    env.connect()
    env.app.post(f"/businesses/{MAYA}/inbox/sync")
    [s] = [s for s in env.overview()["suggestions"] if s["key"] == "email:em-021"]
    assert s["needs_verification"] and "bank_detail_change" in s["flags"] and s["call_script"]
    r = env.app.post(env.url("/payments/requests"), json={"source": "email:em-021"})
    assert r.status_code == 422
    # Bypassing the screen: a request row for that email, proposed straight to the gateway, is still refused.
    store = env.rt.payments.store(MAYA)
    from app.services.payment_store import PaymentRequest
    from datetime import date
    account = env.rt.gateway(MAYA).payee_account("sup_ggw")
    store.add(PaymentRequest(id="pr_00000000000000aa", created_on=date(2026, 10, 19), payee_id="sup_ggw",
                             payee_name="Golden Grain Wholesale", amount_minor=677_176, currency=s["currency"],
                             reference="GGW-26-0099", reason="x", source_kind="email", source_label="x",
                             amount_untrusted=True, email_id="em-021", status="proposed"))
    direct = propose(env.app, MAYA, "pay_invoice", untrusted=("amount_minor",), payee_id="sup_ggw",
                     account_token=account, amount_minor=677_176, reference="GGW-26-0099",
                     request_id="pr_00000000000000aa")
    assert direct["status"] == "denied" and direct["rule"] == "call_script_verification_required"
    store.update("pr_00000000000000aa", status="cancelled")
    # After the owner marks the call done it still needs a signature, and pays the account on file, not the email's.
    assert env.app.post(env.url("/payments/verifications"), json={"email_id": "em-021"}).status_code == 204
    req = env.create(source="email:em-021")
    assert req["status"] == "awaiting_approval" and req["account_token"] == account
    attack.caught("gateway", direct["rule"])


def test_disconnect_revokes_the_token_at_the_provider(make, attack):
    attack("ATK-PAY-REVOKED", "use the payment token after the owner disconnected", "scripted")
    env = make()
    env.connect()
    token = env.rt.payments._token(MAYA)
    req = env.create(source=INVOICE)
    status = env.app.post(env.url("/connections/payments/disconnect")).json()
    assert status["state"] == "not_connected"
    r = env.provider_client.get("/v1/connection", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401 and r.json()["error"] == "token_revoked"
    env.approve(req)
    assert env.get(req["id"])["rule"] == "not_connected" and _provider_payments(env) == 0
    assert [e.data["revoked"] for e in env.rt.audit.entries() if e.kind == "payments.provider_disconnected"] == [True]
    attack.caught("provider", "token_revoked")


def test_forged_webhook_changes_nothing(make, attack):
    attack("ATK-PAY-FORGED-WEBHOOK", "fake 'settled' webhook, and a signed one with a different amount", "scripted")
    env = make()
    env.connect()
    env.drop_webhooks = True
    req = env.create(source=INVOICE)
    env.approve(req)
    pid = env.get(req["id"])["provider_payment_id"]
    event = {"type": "payment.settled", "payment": {"id": pid, "amount_minor": 128_718,
                                                    "idempotency_key": req["id"], "status": "settled"}}
    body = json.dumps(event).encode()
    url = f"/payments/sandboxpay/webhook/{MAYA}"
    forged = env.app.post(url, content=body, headers={"X-SandboxPay-Signature": "sha256=" + "0" * 64})
    unsigned = env.app.post(url, content=body)
    assert forged.status_code == 401 and unsigned.status_code == 401
    from sandboxpay.provider import sign_body
    secret = env.rt.payments._cipher().decrypt(env.rt.payments.connection_store(MAYA).get().webhook_secret_enc)
    wrong = json.dumps({**event, "payment": {**event["payment"], "amount_minor": 1}}).encode()
    mismatch = env.app.post(url, content=wrong, headers={"X-SandboxPay-Signature": sign_body(secret, wrong)})
    assert mismatch.json()["outcome"] == "mismatch"
    assert env.get(req["id"])["status"] == "sent" and env.ledger_rows(req["id"]) == []
    assert "payments.webhook_rejected" in env.audit_kinds()
    attack.caught("webhook", "bad_signature")


def test_provider_enforces_its_own_caps_without_the_gateway(make, attack):
    attack("ATK-PAY-BYPASS-GATEWAY", "compromised app calls the provider directly above the approved caps",
           "scripted")
    env = make()
    env.connect(per_payment=1000, daily=1500)  # the owner approved at most 1000 per payment, 1500 a day
    token = env.rt.payments._token(MAYA)
    currency = env.overview()["connection"]["currency"]

    def pay(key: str, amount: int):
        return env.provider_client.post("/v1/payments", headers={"Authorization": f"Bearer {token}",
                                                                 "Idempotency-Key": key},
                                        json={"payee_ref": "x", "payee_name": "x", "account_token": "acct_x",
                                              "amount_minor": amount, "currency": currency, "reference": "r"})

    assert pay("key-over-cap-1", 100_001).json()["error"] == "over_per_payment_cap"
    assert pay("key-in-cap-001", 100_000).status_code == 202
    assert pay("key-daily-cap1", 60_000).json()["error"] == "over_daily_cap"
    # Through the app: an approved payment above the provider's cap fails there, and nothing is posted.
    req = env.create(source=INVOICE)
    env.approve(req)
    done = env.get(req["id"])
    assert done["status"] == "failed" and done["rule"] == "over_per_payment_cap"
    assert env.ledger_rows(req["id"]) == []
    attack.caught("provider", "over_per_payment_cap")


def test_planner_cannot_propose_a_payment_from_the_payments_tab(attack):
    attack("ATK-PAY-PLANNER", "the assistant proposes pay_invoice itself", "scripted")
    from app.agent.actions import propose_action

    seen, event = propose_action(None, json.dumps({"tool": "pay_invoice", "args": {}, "reason": "pay it"}))
    assert "not available to the assistant" in seen["error"] and event is None
    assert PaymentsService  # the Payments service is the only proposer of pay_invoice
    attack.caught("planner", "not_for_planner")
