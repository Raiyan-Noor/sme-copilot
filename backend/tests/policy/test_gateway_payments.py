"""Policy boundaries for payments: `pay_invoice` is always T3 and bound to the payee's current account on file;
`mandate_covers` is a read-only preview of the T2 rules that never runs or logs anything; the raised bill cap is a
hard ceiling at exactly its value."""

import pytest

from app.gateway import load_policy
from tests.gateway_env import action

BILL_CAP = load_policy().t2["pay_recurring_bill"].max_amount_minor
ACCOUNT = "acct_citygrid_on_file"


def _set_account(env, payee: str, account: str) -> None:
    change = env.gateway.propose(action("change_payee_details", payee_id=payee, account_token=account))
    assert env.approve(change, out_of_band_confirmed=True).status == "executed"


def _pay(**overrides):
    args = {"payee_id": "pay_citygrid", "account_token": ACCOUNT, "amount_minor": 34_000, "reference": "INV-1",
            "request_id": "pr_0000000000000001", **overrides}
    return action("pay_invoice", **args)


def test_bill_cap_is_the_owner_chosen_value():
    assert BILL_CAP == 500_000
    assert load_policy().t2["send_invoice_reminder"].max_amount_minor == 50_000  # reminders unchanged


def test_pay_invoice_always_waits_for_a_signature(env):
    _set_account(env, "pay_citygrid", ACCOUNT)
    env.grant("pay_recurring_bill", BILL_CAP, ("pay_citygrid",))  # a mandate does not cover pay_invoice
    d = env.gateway.propose(_pay())
    assert d.status == "pending_approval" and d.tier == "T3" and d.rule == "tier_T3"


def test_pay_invoice_signed_runs_once(env):
    _set_account(env, "pay_citygrid", ACCOUNT)
    d = env.gateway.propose(_pay())
    done = env.approve(d)
    assert done.status == "executed"
    assert done.result["idempotency_key"] == "pr_0000000000000001"
    assert done.result["provider_status"] == "not_sent" and done.result["reason"] == "not_connected"  # no provider
    assert env.approve(d).status == "denied"


def test_pay_invoice_to_an_account_not_on_file_is_denied(env):
    _set_account(env, "pay_citygrid", ACCOUNT)
    d = env.gateway.propose(_pay(account_token="acct_from_an_email"))
    assert d.status == "denied" and d.rule == "payee_account_changed"


def test_account_change_between_request_and_signature_is_denied(env):
    _set_account(env, "pay_citygrid", ACCOUNT)
    d = env.gateway.propose(_pay())
    _set_account(env, "pay_citygrid", "acct_new")
    assert env.approve(d).rule == "payee_account_changed"
    assert [op["kind"] for op in env.bank_ops] == ["payee_change", "payee_change"]


@pytest.mark.parametrize("bad", [{"amount_minor": "34000"}, {"request_id": 7}, {"extra": "x"}])
def test_pay_invoice_with_bad_args_is_denied(env, bad):
    d = env.gateway.propose(_pay(**bad))
    assert d.status == "denied" and d.rule.startswith("bad_args")


def test_mandate_covers_is_read_only_and_matches_propose(env):
    env.grant("pay_recurring_bill", 10_000, ("pay_citygrid",))
    within = action("pay_recurring_bill", payee_id="pay_citygrid", bill_id="b1", amount_minor=10_000)
    above = action("pay_recurring_bill", payee_id="pay_citygrid", bill_id="b2", amount_minor=10_001)
    other = action("pay_recurring_bill", payee_id="pay_elmwood", bill_id="b3", amount_minor=100)
    untrusted = action("pay_recurring_bill", untrusted=("amount_minor",), payee_id="pay_citygrid", bill_id="b4",
                       amount_minor=100)
    before = len(list(env.audit.entries()))
    assert env.gateway.mandate_covers(within)
    assert not any(env.gateway.mandate_covers(a) for a in (above, other, untrusted, _pay()))
    assert len(list(env.audit.entries())) == before and env.bank_ops == []
    assert env.gateway.propose(within).status == "executed"
    assert env.gateway.propose(above).status == "denied"
