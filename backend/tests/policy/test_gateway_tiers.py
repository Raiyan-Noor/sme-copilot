"""Tier boundaries: unknown/T4/system tools denied, T1 not an action, T2 needs a mandate, T3 always waits for the
owner, untrusted provenance forces T3 (invariants 1, 3, 5)."""

import pytest
from pydantic import ValidationError

from app.gateway import ProposedAction
from tests.gateway_env import action, bill, loan_application, reminder

pytestmark = pytest.mark.policy


@pytest.mark.parametrize("tool", ["take_large_loan", "fire_employee", "change_prices", "sign_supplier_deal",
                                  "transfer_funds", "PAY_RECURRING_BILL", "pay_recurring_bill_v2"])
def test_unknown_and_t4_tools_denied_and_logged_as_violation(env, tool):
    d = env.gateway.propose(action(tool))
    assert d.status == "denied" and d.rule == "unknown_tool"
    kinds = [e.kind for e in env.audit.entries()]
    assert "gateway.violation" in kinds
    assert env.bank_ops == [] and env.outbox == []


def test_system_anchor_tool_not_proposable(env):
    d = env.gateway.propose(action("anchor"))
    assert d.status == "denied" and d.rule == "system_tool"


@pytest.mark.parametrize("tool", ["get_cash_position", "list_transactions", "explain_fact", "get_passport"])
def test_t1_tools_are_not_actions(env, tool):
    d = env.gateway.propose(action(tool))
    assert d.status == "denied" and d.tier == "T1" and d.rule == "t1_is_not_an_action"


def test_provenance_is_required():
    with pytest.raises(ValidationError):
        ProposedAction(tool="pay_recurring_bill", args={"payee_id": {"value": "pay_citygrid"}})
    with pytest.raises(ValidationError):
        ProposedAction(tool="pay_recurring_bill", args={"payee_id": {"value": "x", "provenance": "owner"}})


@pytest.mark.parametrize("args, fragment", [
    ({"payee_id": "pay_citygrid", "bill_id": "bill_power"}, "missing=amount_minor"),
    ({"payee_id": "pay_citygrid", "bill_id": "bill_power", "amount_minor": 1, "memo": "x"}, "extra=memo"),
    ({"payee_id": "pay_citygrid", "bill_id": "bill_power", "amount_minor": "100"}, "amount_minor must be int"),
    ({"payee_id": "pay_citygrid", "bill_id": "bill_power", "amount_minor": True}, "amount_minor must be int"),
])
def test_bad_args_denied_before_anything_else(env, args, fragment):
    env.grant("pay_recurring_bill", 50_000, ("pay_citygrid",))
    d = env.gateway.propose(action("pay_recurring_bill", **args))
    assert d.status == "denied" and fragment in d.rule
    assert env.bank_ops == []


def test_t2_without_standing_mandate_denied(env):
    d = env.gateway.propose(bill())
    assert d.status == "denied" and d.rule == "no_standing_mandate"
    assert env.bank_ops == []


def test_t2_within_mandate_executes(env):
    m = env.grant("pay_recurring_bill", 50_000, ("pay_citygrid",))
    d = env.gateway.propose(bill())
    assert d.status == "executed" and d.mandate_id == m.id
    assert env.bank_ops[0]["payee_id"] == "pay_citygrid" and env.bank_ops[0]["amount_minor"] == 34_000


def test_mandate_for_one_tool_does_not_cover_another(env):
    env.grant("pay_recurring_bill", 50_000, ("cus_sunrise",))
    d = env.gateway.propose(reminder())
    assert d.status == "denied" and d.rule == "no_standing_mandate"


@pytest.mark.parametrize("tool_action", [
    lambda env: loan_application(env.gateway),
    lambda env: action("change_payee_details", payee_id="pay_citygrid", account_token="acct_tok_1"),
    lambda env: action("delay_supplier_payment", payment_ref="pmt_1", new_date="2026-10-25"),
    lambda env: action("send_supplier_message", supplier_id="sup_fl", template_id="tpl_delay"),
    lambda env: action("cancel_subscription", subscription_id="sub_1"),
])
def test_t3_always_pending_even_with_trusted_args(env, tool_action):
    d = env.gateway.propose(tool_action(env))
    assert d.status == "pending_approval" and d.tier == "T3" and d.effective_tier == "T3"
    assert d.approval.payload.action == d.tool
    assert env.bank_ops == [] and env.outbox == []


def test_untrusted_amount_forces_t3_even_within_mandate(env):
    env.grant("pay_recurring_bill", 50_000, ("pay_citygrid",))
    d = env.gateway.propose(bill(untrusted=("amount_minor",)))
    assert d.status == "pending_approval" and d.tier == "T2" and d.effective_tier == "T3"
    assert d.rule == "untrusted_provenance:amount_minor"
    assert env.bank_ops == []


@pytest.mark.parametrize("field", ["payee_id", "bill_id"])
def test_untrusted_payee_or_reference_forces_t3(env, field):
    env.grant("pay_recurring_bill", 50_000, ("pay_citygrid",))
    d = env.gateway.propose(bill(untrusted=(field,)))
    assert d.status == "pending_approval" and field in d.rule


def test_untrusted_escalation_still_needs_signature_then_executes(env):
    d = env.gateway.propose(bill(amount=999_999, untrusted=("amount_minor",)))
    assert d.status == "pending_approval"
    done = env.approve(d)
    assert done.status == "executed" and env.bank_ops[0]["amount_minor"] == 999_999


def test_untrusted_payee_change_still_requires_out_of_band_call(env):
    d = env.gateway.propose(action("change_payee_details", untrusted=("account_token",),
                                   payee_id="pay_citygrid", account_token="acct_attacker"))
    assert d.approval.requires_out_of_band_call_script
    assert env.approve(d).rule == "out_of_band_call_required"
    assert env.approve(d, out_of_band_confirmed=True).status == "executed"
    assert env.gateway.executors.bank.payee_account("pay_citygrid") == "acct_attacker"


def test_every_decision_is_audited(env):
    env.gateway.propose(action("fire_employee"))
    env.gateway.propose(bill())
    env.gateway.propose(action("cancel_subscription", subscription_id="sub_1"))
    decisions = [e.data for e in env.audit.entries() if e.kind == "gateway.decision"]
    assert [(x["tool"], x["status"]) for x in decisions] == [
        ("fire_employee", "denied"), ("pay_recurring_bill", "denied"), ("cancel_subscription", "pending_approval")]
    assert env.audit.verify().ok
