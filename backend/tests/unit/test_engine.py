"""Engine calculators on a tiny hand-built ledger, where every expected number can be worked out by hand."""

from datetime import date, timedelta

import pytest

from app.clock import FixedClock
from app.engine.cash import buffer_days, cash_balance
from app.engine.forecast import forecast, runway
from app.engine.margins import product_margins
from app.engine.pack_inputs import CategorySpec, EnginePack, HolidayWindow
from app.engine.pnl import gross_margin, pnl_by_period
from app.ledger.pos import Product, SaleLine
from app.ledger.scheduled import ScheduledItem
from app.ledger.snapshot import LedgerSnapshot, Transaction

TODAY = date(2026, 3, 2)  # a Monday
CLOCK = FixedClock(TODAY)

PACK = EnginePack(
    pack_id="test",
    categories={
        "sales": CategorySpec(kind="revenue"),
        "customer_payment": CategorySpec(kind="revenue", scheduled=True),
        "inventory": CategorySpec(kind="cogs"),
        "fees": CategorySpec(kind="operating"),
        "rent": CategorySpec(kind="operating", scheduled=True),
        "owner_drawings": CategorySpec(kind="owner", scheduled=True),
    },
)


def _txn(i: int, d: date, amount: int, category: str | None, account: str = "acct_bank",
         balance: int | None = None) -> Transaction:
    return Transaction(id=f"txn_{i:04d}", account_id=account, posted_on=d, amount_minor=amount, currency="USD",
                       description="synthetic", category=category, balance_minor=balance, import_id="imp_1",
                       source_line=i)


def _ledger() -> LedgerSnapshot:
    """Opening 1,000.00; 60 days of 100.00 sales; 60.00 supplier payment on Mondays; rent 500.00 on Feb 1;
    one uncategorized 2,000.00 inflow (a loan) and one owner drawing."""
    rows, i, bal = [], 0, 100_000
    rows.append(_txn(i, TODAY - timedelta(days=61), 0, None, balance=bal))
    for k in range(60, 0, -1):
        d = TODAY - timedelta(days=k)
        i += 1
        rows.append(_txn(i, d, 10_000, "sales"))
        if d.weekday() == 0:
            i += 1
            rows.append(_txn(i, d, -6_000, "inventory"))
        if d == date(2026, 2, 1):
            i += 1
            rows.append(_txn(i, d, -50_000, "rent"))
        if d == date(2026, 2, 10):
            i += 1
            rows.append(_txn(i, d, 200_000, None))
            i += 1
            rows.append(_txn(i, d, -20_000, "owner_drawings"))
    return LedgerSnapshot(business_id="test-biz", currency="USD", transactions=tuple(rows))


LEDGER = _ledger()
TOTAL = sum(t.amount_minor for t in LEDGER.transactions) + 100_000


def _by_id(facts):
    ids = [f.id for f in facts]
    assert len(ids) == len(set(ids)), "fact IDs must be unique"
    return {f.id: f for f in facts}


def test_cash_balance_from_last_statement_balance_plus_later_rows():
    f = _by_id(cash_balance(LEDGER, CLOCK))
    assert f["cash.balance"].value == TOTAL
    assert f["cash.balance.acct_bank"].value == TOTAL
    assert f["cash.balance"].display.startswith("$")
    # the anchor row plus every later row, nothing earlier
    assert f["cash.balance"].source_row_ids[0] == "txn_0000"
    assert f["cash.last_activity"].value == TODAY - timedelta(days=1)


def test_cash_balance_uses_latest_balance_and_ignores_future_rows():
    rows = (_txn(1, date(2026, 3, 1), 500, "sales", balance=9_000),
            _txn(2, date(2026, 3, 1), -200, "fees"),
            _txn(3, date(2026, 3, 5), 7_777, "sales"))  # after today: not yet happened
    snap = LedgerSnapshot(business_id="t", currency="USD", transactions=rows)
    f = _by_id(cash_balance(snap, CLOCK))
    assert f["cash.balance"].value == 8_800
    assert f["cash.balance"].source_row_ids == ("txn_0001", "txn_0002")


def test_pnl_lines_add_up_and_keep_loans_and_drawings_out():
    f = _by_id(pnl_by_period(LEDGER, PACK, CLOCK))
    feb = "pnl.2026-02"
    assert f[f"{feb}.revenue"].value == 28 * 10_000
    mondays = sum(1 for k in range(28) if date(2026, 2, 1 + k).weekday() == 0)
    assert f[f"{feb}.cogs"].value == mondays * 6_000
    assert f[f"{feb}.gross_profit"].value == f[f"{feb}.revenue"].value - f[f"{feb}.cogs"].value
    assert f[f"{feb}.expense.rent"].value == 50_000
    assert f[f"{feb}.operating_profit"].value == f[f"{feb}.gross_profit"].value - 50_000
    assert f[f"{feb}.owner_drawings"].value == 20_000
    assert f[f"{feb}.uncategorized.inflows"].value == 200_000
    assert f[f"{feb}.gross_margin"].value == pytest.approx(f[f"{feb}.gross_profit"].value / (28 * 10_000), abs=1e-4)
    assert f[f"{feb}.days_covered"].value == 28
    # the month in progress counts completed days only: Mar 1, not today
    assert f["pnl.2026-03.days_covered"].value == 1
    assert f["pnl.2026-03.revenue"].value == 10_000


def test_pnl_by_week_uses_iso_weeks():
    f = _by_id(pnl_by_period(LEDGER, PACK, CLOCK, period="week"))
    assert f["pnl.2026-w09.revenue"].value == 7 * 10_000  # Feb 23 - Mar 1


def test_gross_margin_window():
    f = _by_id(gross_margin(LEDGER, PACK, CLOCK, window_days=28))
    assert f["margin.last_28d.revenue"].value == 28 * 10_000
    assert f["margin.last_28d.cogs"].value == 4 * 6_000
    assert f["margin.last_28d.gross_margin"].value == pytest.approx(1 - 24_000 / 280_000, abs=1e-4)
    assert f["margin.last_28d.start"].value == TODAY - timedelta(days=28)


def test_buffer_days_counts_supplier_and_operating_spend_only():
    f = _by_id(buffer_days(LEDGER, PACK, CLOCK, window_days=28))
    avg = round(4 * 6_000 / 28)  # rent was paid > 28 days ago, drawings are excluded
    assert f["cash.avg_daily_spend.last_28d"].value == avg
    assert f["cash.buffer_days"].value == pytest.approx(round(TOTAL / avg, 1))
    assert f["cash.buffer_days"].inputs == ("cash.balance", "cash.avg_daily_spend.last_28d")


def test_refunds_net_revenue_and_still_count_as_spend():
    """A refund in a revenue category reduces revenue and is still cash leaving, so buffer days count it."""
    refund = _txn(9_999, TODAY - timedelta(days=3), -2_800, "sales")
    snap = LEDGER.model_copy(update={"transactions": LEDGER.transactions + (refund,)})
    pnl = _by_id(pnl_by_period(snap, PACK, CLOCK))
    assert pnl["pnl.2026-02.revenue"].value == 28 * 10_000 - 2_800
    f = _by_id(buffer_days(snap, PACK, CLOCK, window_days=28))
    assert f["cash.avg_daily_spend.last_28d"].value == round((4 * 6_000 + 2_800) / 28)


def test_forecast_steady_business_is_exact_and_band_collapses():
    """Constant sales and Monday payments: residuals are zero, so low == expected == high without receivables."""
    rent = ScheduledItem(id="sch_rent", kind="payable", category="rent", due_date=date(2026, 3, 10),
                         amount_minor=50_000)
    f = _by_id(forecast(LEDGER, PACK, CLOCK, (rent,)))
    mondays = sum(1 for k in range(30) if (TODAY + timedelta(days=k)).weekday() == 0)
    want = TOTAL + 30 * 10_000 - mondays * 6_000 - 50_000
    assert f["forecast.30d.end_balance"].value == want
    assert f["forecast.30d.end_balance_low"].value == want
    assert f["forecast.30d.end_balance_high"].value == want
    assert f["forecast.band.daily_sigma"].value == 0
    assert f["forecast.baseline.mon.outflow"].value == 6_000
    assert f["forecast.baseline.tue.outflow"].value == 0
    assert f["forecast.30d.scheduled_out"].value == 50_000
    assert f["forecast.30d.end_date"].value == TODAY + timedelta(days=29)
    assert "sch_rent" in f["forecast.30d.end_balance"].source_row_ids
    assert f["forecast.daily.2026-03-09.expected"].value - f["forecast.daily.2026-03-10.expected"].value \
        == 50_000 - 10_000


def test_forecast_rent_history_is_not_double_counted():
    """Rent is a scheduled category: its history stays out of the baseline, so with no scheduled rent the
    forecast has no rent at all."""
    f = _by_id(forecast(LEDGER, PACK, CLOCK, ()))
    mondays = sum(1 for k in range(30) if (TODAY + timedelta(days=k)).weekday() == 0)
    assert f["forecast.30d.end_balance"].value == TOTAL + 30 * 10_000 - mondays * 6_000


def test_forecast_receivables_shape_the_band():
    due = ScheduledItem(id="sch_due", kind="receivable", category="customer_payment",
                        due_date=date(2026, 3, 5), amount_minor=30_000)
    late = ScheduledItem(id="sch_late", kind="receivable", category="customer_payment",
                         due_date=date(2026, 2, 1), amount_minor=40_000)
    paid = ScheduledItem(id="sch_paid", kind="receivable", category="customer_payment",
                         due_date=date(2026, 3, 6), amount_minor=99_000, status="paid")
    supplier = ScheduledItem(id="sch_sup", kind="payable", category="inventory",
                             due_date=date(2026, 3, 6), amount_minor=8_000)
    base = _by_id(forecast(LEDGER, PACK, CLOCK, ()))["forecast.30d.end_balance"].value
    f = _by_id(forecast(LEDGER, PACK, CLOCK, (due, late, paid, supplier)))
    assert f["forecast.30d.end_balance"].value == base + 30_000  # overdue, paid and baseline-covered items left out
    assert f["forecast.30d.end_balance_low"].value == base  # low path collects nothing
    assert f["forecast.30d.end_balance_high"].value == base + 30_000 + 40_000  # high path collects the overdue due
    assert f["forecast.overdue_receivables"].value == 40_000
    assert f["forecast.scheduled.in_baseline.count"].value == 1


def test_forecast_applies_seasonality_and_deseasonalizes_history():
    pack = PACK.model_copy(update={
        "month_multipliers": {3: 1.0},
        "holidays": (HolidayWindow(id="major_festival", name="Festival", start=date(2026, 3, 4),
                                   end=date(2026, 3, 4), multiplier=2.0),
                     # a past holiday window: history on that day is divided by 2 before averaging
                     HolidayWindow(id="major_festival", name="Festival", start=date(2026, 2, 4),
                                   end=date(2026, 2, 4), multiplier=2.0)),
    })
    f = _by_id(forecast(LEDGER, pack, CLOCK, ()))
    plain = _by_id(forecast(LEDGER, PACK, CLOCK, ()))
    day = lambda facts, d: facts[f"forecast.daily.{d}.expected"].value  # noqa: E731
    jump = day(f, "2026-03-04") - day(f, "2026-03-03")
    assert jump > day(plain, "2026-03-04") - day(plain, "2026-03-03")
    assert f["forecast.band.daily_sigma"].value > 0  # the deseasonalized holiday day is now an outlier


def test_runway_on_expected_and_stressed_paths():
    big = ScheduledItem(id="sch_tax", kind="payable", category="rent", due_date=date(2026, 3, 20),
                        amount_minor=TOTAL + 2_000_000)
    f = _by_id(runway(LEDGER, PACK, CLOCK, (big,)))
    assert f["runway.date"].value == date(2026, 3, 20)
    assert f["runway.days"].value == 18
    assert f["runway.stressed.days"].value == 18
    ok = _by_id(runway(LEDGER, PACK, CLOCK, ()))
    assert ok["runway.days"].value is None
    assert ok["runway.days"].display == "more than 90 days"


def test_product_margins():
    products = (Product(id="rice_5kg", name="Rice", price_minor=1_200),
                Product(id="water", name="Water", price_minor=100))
    lines = (SaleLine(id="sl_1", date=date(2026, 2, 20), product_id="rice_5kg", qty=10, revenue_minor=12_000,
                      cost_minor=9_000),
             SaleLine(id="sl_2", date=date(2026, 2, 21), product_id="rice_5kg", qty=-1, revenue_minor=-1_200,
                      cost_minor=-900),
             SaleLine(id="sl_3", date=date(2026, 2, 21), product_id="water", qty=5, revenue_minor=500,
                      cost_minor=600),
             SaleLine(id="sl_4", date=date(2025, 1, 1), product_id="water", qty=99, revenue_minor=9_900,
                      cost_minor=1))  # outside the window
    f = _by_id(product_margins(products, lines, CLOCK, "USD", window_days=90))
    assert f["margin.product.rice_5kg.last_90d.units"].value == 9
    assert f["margin.product.rice_5kg.last_90d.gross_profit"].value == 10_800 - 8_100
    assert f["margin.product.rice_5kg.last_90d.margin"].value == 0.25
    assert f["margin.product.water.last_90d.margin"].value == -0.2
    assert f["margin.product.water.last_90d.margin"].display == "-20.0%"


def test_engine_is_pure_and_every_fact_traces():
    before = LEDGER.model_copy(deep=True)
    runs = [
        pnl_by_period(LEDGER, PACK, CLOCK) + gross_margin(LEDGER, PACK, CLOCK) + buffer_days(LEDGER, PACK, CLOCK)
        + forecast(LEDGER, PACK, CLOCK) + runway(LEDGER, PACK, CLOCK)
        for _ in range(2)
    ]
    assert runs[0] == runs[1]
    assert LEDGER == before
    row_ids = {t.id for t in LEDGER.transactions}
    for fact in runs[0]:
        assert fact.source_row_ids or fact.inputs, fact.id
        unknown = [s for s in fact.source_row_ids if s not in row_ids and not s.startswith(("clock:", "sch_"))]
        assert not unknown, (fact.id, unknown[:3])


def test_core_facts_emits_each_fact_once():
    from app.engine.core import core_facts

    facts = core_facts(LEDGER, PACK, CLOCK)
    assert len({f.id for f in facts}) == len(facts)
    assert {"cash.balance", "cash.buffer_days", "forecast.90d.end_balance", "runway.days"} <= {f.id for f in facts}
