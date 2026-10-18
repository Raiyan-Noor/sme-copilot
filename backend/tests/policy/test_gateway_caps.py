"""T2 hard caps: amount ceilings (policy and mandate), allow-lists, frequency window, mandate expiry."""

from datetime import timedelta

import pytest

from app.gateway import load_policy
from tests.gateway_env import bill, reminder

pytestmark = pytest.mark.policy

POLICY = load_policy()
BILL_CAP = POLICY.t2["pay_recurring_bill"].max_amount_minor
REMINDER_CAP = POLICY.t2["send_invoice_reminder"].max_amount_minor


def test_amount_at_policy_cap_executes_and_one_over_is_denied(env):
    env.grant("pay_recurring_bill", BILL_CAP, ("pay_citygrid",))
    assert env.gateway.propose(bill(amount=BILL_CAP)).status == "executed"
    d = env.gateway.propose(bill(amount=BILL_CAP + 1))
    assert d.status == "denied" and d.rule == "over_policy_cap"
    assert len(env.bank_ops) == 1


def test_reminder_invoice_over_policy_cap_denied(env):
    env.grant("send_invoice_reminder", REMINDER_CAP, ("cus_sunrise",))
    d = env.gateway.propose(reminder(amount=REMINDER_CAP + 1))
    assert d.status == "denied" and d.rule == "over_policy_cap"
    assert env.outbox == []


def test_mandate_cap_lowers_policy_cap(env):
    env.grant("pay_recurring_bill", 10_000, ("pay_citygrid", "pay_metrowater"))
    assert env.gateway.propose(bill("pay_metrowater", 6_500, "bill_water")).status == "executed"
    assert env.gateway.propose(bill("pay_metrowater", 10_000, "bill_water")).status == "executed"
    d = env.gateway.propose(bill("pay_citygrid", 10_001))
    assert d.status == "denied" and d.rule == "over_mandate_cap"


def test_payee_not_in_signed_allowlist_denied(env):
    env.grant("pay_recurring_bill", BILL_CAP, ("pay_citygrid",))
    d = env.gateway.propose(bill("pay_unknown_vendor", 100))
    assert d.status == "denied" and d.rule == "not_allowlisted:payee_id"
    assert env.bank_ops == []


def test_customer_not_in_signed_allowlist_denied(env):
    env.grant("send_invoice_reminder", REMINDER_CAP, ("cus_sunrise", "cus_littlesteps"))
    d = env.gateway.propose(reminder("cus_greenleaf", 21_400))
    assert d.status == "denied" and d.rule == "not_allowlisted:customer_id"


def test_reminder_frequency_one_per_customer_per_three_days(env):
    env.grant("send_invoice_reminder", REMINDER_CAP, ("cus_sunrise", "cus_littlesteps"))
    assert env.gateway.propose(reminder("cus_sunrise")).status == "executed"
    # Same customer, even a different invoice, is blocked for the rest of the window.
    for day in (0, 1, 2):
        if day:
            env.clock.advance(1)
        d = env.gateway.propose(reminder("cus_sunrise", invoice_id=f"INV-{day + 2}"))
        assert d.status == "denied" and d.rule == "frequency_cap", day
    # Other customers are independent.
    assert env.gateway.propose(reminder("cus_littlesteps")).status == "executed"
    env.clock.advance(1)  # day 3: window over
    assert env.gateway.propose(reminder("cus_sunrise")).status == "executed"
    assert len(env.outbox) == 3


def test_recurring_bill_has_no_frequency_cap(env):
    env.grant("pay_recurring_bill", BILL_CAP, ("pay_citygrid",))
    assert [env.gateway.propose(bill()).status for _ in range(3)] == ["executed"] * 3


def test_standing_mandate_valid_through_expiry_day_then_denied(env):
    env.grant("pay_recurring_bill", BILL_CAP, ("pay_citygrid",), days=5)
    env.clock.advance(5)
    assert env.gateway.propose(bill()).status == "executed"
    env.clock.advance(1)
    d = env.gateway.propose(bill())
    assert d.status == "denied" and d.rule == "no_standing_mandate"


def test_newer_mandate_replaces_older_one(env):
    env.grant("pay_recurring_bill", BILL_CAP, ("pay_citygrid",))
    env.grant("pay_recurring_bill", 1_000, ("pay_citygrid",))
    d = env.gateway.propose(bill(amount=2_000))
    assert d.status == "denied" and d.rule == "over_mandate_cap"


def test_expiry_window_is_measured_from_today(env):
    m = env.grant("pay_recurring_bill", BILL_CAP, ("pay_citygrid",), days=1)
    assert m.payload.expiry == env.clock.today() + timedelta(days=1)
