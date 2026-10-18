"""Gateway over HTTP: owner key enrolment (trust on first use), T3 approval signed in the "browser" (the test's
key), T2 standing mandates with caps, replay and wrong-signer rejection, and every decision in the audit log."""

import pytest

from app.audit.canonical import canonical_json
from tests.api.conftest import MAYA, api_client
from tests.gateway_env import Owner

GW = f"/businesses/{MAYA}/gateway"


def _arg(value, provenance="trusted"):
    return {"value": value, "provenance": provenance}


def _propose(api, tool, untrusted=(), **args):
    body = {"tool": tool, "args": {k: _arg(v, "untrusted" if k in untrusted else "trusted") for k, v in args.items()}}
    r = api.post(f"{GW}/propose", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def _approve(api, decision, owner, **extra):
    approval_id = decision["approval"]["approval_id"]
    view = api.get(f"{GW}/approvals/{approval_id}").json()
    signature = owner.key.sign(view["message"].encode()).signature.hex()
    return api.post(f"{GW}/approvals/{approval_id}/approve",
                    json={"signature": signature, "public_key": owner.public_key, **extra})


def _grant(api, owner, action, max_amount_minor, allowlist, days=30):
    draft = api.post(f"{GW}/mandates/draft", json={
        "action": action, "terms": {"max_amount_minor": max_amount_minor, "allowlist": allowlist}, "days": days,
    }).json()
    signature = owner.key.sign(draft["message"].encode()).signature.hex()
    return api.post(f"{GW}/mandates", json={"payload": draft["payload"], "terms": draft["terms"],
                                            "signature": signature, "public_key": owner.public_key}).json()


@pytest.fixture
def owner(api) -> Owner:
    owner = Owner()
    r = api.post(f"{GW}/owner-key", json={"public_key": owner.public_key})
    assert r.status_code == 200 and r.json()["enrolled"]
    return owner


def test_owner_key_is_trust_on_first_use(api, owner):
    assert api.post(f"{GW}/owner-key", json={"public_key": owner.public_key}).status_code == 200
    intruder = Owner(seed=b"\x02" * 32)
    assert api.post(f"{GW}/owner-key", json={"public_key": intruder.public_key}).status_code == 409
    rejected = api.get("/audit", params={"kind": "gateway.key_rejected"}).json()["entries"]
    assert rejected[0]["data"]["rule"] == "owner_key_already_enrolled"
    assert api.post(f"{GW}/owner-key", json={"public_key": "zz" * 32}).status_code == 422


def test_t3_action_waits_for_signature_then_executes_once(api, owner):
    decision = _propose(api, "cancel_subscription", subscription_id="sub_pos_b")
    assert decision["status"] == "pending_approval" and decision["effective_tier"] == "T3"

    view = api.get(f"{GW}/approvals/{decision['approval']['approval_id']}").json()
    assert view["status"] == "pending" and view["args"] == {"subscription_id": "sub_pos_b"}
    assert view["message"].encode() == canonical_json(view["payload"])

    executed = _approve(api, decision, owner)
    assert executed.status_code == 200 and executed.json()["status"] == "executed"
    replay = _approve(api, decision, owner).json()
    assert replay["status"] == "denied" and replay["rule"] == "replayed_nonce"


def test_signature_from_an_unenrolled_key_is_denied(api, owner):
    decision = _propose(api, "cancel_subscription", subscription_id="sub_pos_b")
    denied = _approve(api, decision, Owner(seed=b"\x03" * 32)).json()
    assert denied["status"] == "denied" and denied["rule"] == "unknown_signer"


def test_tampered_signature_is_denied(api, owner):
    decision = _propose(api, "cancel_subscription", subscription_id="sub_pos_b")
    approval_id = decision["approval"]["approval_id"]
    message = api.get(f"{GW}/approvals/{approval_id}").json()["message"]
    bad = owner.key.sign((message + " ").encode()).signature.hex()  # signs different bytes
    denied = api.post(f"{GW}/approvals/{approval_id}/approve",
                      json={"signature": bad, "public_key": owner.public_key}).json()
    assert denied["rule"] == "bad_signature"


def test_expired_approval_is_denied(api, owner):
    decision = _propose(api, "cancel_subscription", subscription_id="sub_pos_b")
    api.post("/clock/advance", json={"days": 3})  # approvals live two days
    assert _approve(api, decision, owner).json()["rule"] == "expired"


def test_payee_change_needs_the_out_of_band_call(api, owner):
    decision = _propose(api, "change_payee_details", payee_id="sup_ggw", account_token="acct_abcdefghijkl")
    assert decision["approval"]["requires_out_of_band_call_script"] is True
    assert _approve(api, decision, owner).json()["rule"] == "out_of_band_call_required"


def test_t2_runs_only_under_a_signed_standing_mandate(api, owner):
    no_mandate = _propose(api, "send_invoice_reminder", customer_id="cus_sunrise", invoice_id="INV-1",
                          invoice_amount_minor=38_650)
    assert no_mandate["status"] == "denied" and no_mandate["rule"] == "no_standing_mandate"

    granted = _grant(api, owner, "send_invoice_reminder", 40_000, ["cus_sunrise"])
    assert granted["accepted"] and granted["mandate"]["record_hash"]

    ok = _propose(api, "send_invoice_reminder", customer_id="cus_sunrise", invoice_id="INV-1",
                  invoice_amount_minor=38_650)
    assert ok["status"] == "executed" and ok["mandate_id"] == granted["mandate"]["id"]
    again = _propose(api, "send_invoice_reminder", customer_id="cus_sunrise", invoice_id="INV-1",
                     invoice_amount_minor=38_650)
    assert again["rule"] == "frequency_cap"
    over = _propose(api, "send_invoice_reminder", customer_id="cus_sunrise", invoice_id="INV-2",
                    invoice_amount_minor=40_001)
    assert over["status"] == "denied"
    stranger = _propose(api, "send_invoice_reminder", customer_id="cus_other", invoice_id="INV-3",
                        invoice_amount_minor=100)
    assert stranger["rule"] == "not_allowlisted:customer_id"


def test_mandate_cannot_raise_the_policy_cap(api, owner):
    result = _grant(api, owner, "pay_recurring_bill", 10_000_000, ["pay_citygrid"])
    assert result == {"accepted": False, "rule": "raises_policy_cap", "mandate": None}


def test_untrusted_value_forces_owner_approval(api, owner):
    _grant(api, owner, "pay_recurring_bill", 50_000, ["pay_citygrid"])
    decision = _propose(api, "pay_recurring_bill", untrusted=("amount_minor",), payee_id="pay_citygrid",
                        bill_id="bill_power", amount_minor=34_000)
    assert decision["status"] == "pending_approval" and decision["tier"] == "T2"
    assert decision["effective_tier"] == "T3"


def test_unknown_and_t4_like_tools_are_denied_and_logged(api):
    for tool in ("wire_money", "anchor", "get_cash_position"):
        assert _propose(api, tool)["status"] == "denied"
    rules = [e["data"]["rule"] for e in api.get("/audit", params={"kind": "gateway.violation"}).json()["entries"]]
    assert sorted(rules) == ["system_tool", "unknown_tool"]


def test_every_decision_is_in_a_valid_audit_chain(api, owner):
    decision = _propose(api, "cancel_subscription", subscription_id="sub_pos_b")
    _approve(api, decision, owner)
    kinds = {e["kind"] for e in api.get("/audit", params={"kind": "gateway."}).json()["entries"]}
    assert {"gateway.key_enrolled", "gateway.decision", "gateway.approval", "gateway.mandate_stored"} <= kinds
    assert api.get("/audit/verify").json()["ok"] is True


def test_unknown_approval_is_404(api):
    assert api.get(f"{GW}/approvals/apr_0000000000000000").status_code == 404
    assert api.get(f"{GW}/approvals/not-an-id").status_code == 422


def test_propose_route_is_absent_without_test_routes(data_dir, seed_dir):
    locked = api_client(data_dir, seed_dir, expose_test_routes=False)
    r = locked.post(f"{GW}/propose", json={"tool": "cancel_subscription", "args": {}})
    assert r.status_code in (404, 405)
