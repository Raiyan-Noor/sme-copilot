"""Swapping the Skill Pack changes outputs on the same ledger: categories, seasonality, KPIs and benchmarks,
leak findings, financing fit and readiness. Every leak and KPI Fact traces to rows of that ledger.
"""

from datetime import date, timedelta

import pytest

from app.engine.pack_inputs import build_engine_pack
from app.firewall.fact import Fact
from app.packs.benchmarks import benchmark, compute_kpis
from app.packs.financing import financing_fit, rank_product_types
from app.packs.leaks import find_leaks, run_leak_detectors
from app.packs.ledger_view import UNCATEGORIZED, categorize_snapshot, frame
from app.packs.loader import load_pack
from app.packs.readiness import readiness_score
from app.packs.registry import DetectorContext, get_detector
from tests.pack_ledger import CLOCK, CURRENCY, DAILY_SALES, POS_CHEAP_MONTHLY, TODAY, build_snapshot, snapshot_of

GROCERY, FASHION = "grocery_retail", "fashion_retail"


@pytest.fixture(scope="module")
def snapshot():
    return build_snapshot()


@pytest.fixture(scope="module")
def packs():
    return load_pack(GROCERY), load_pack(FASHION)


def _category_of(snapshot, pack, description: str) -> str:
    cats = categorize_snapshot(snapshot, pack)
    return next(t.category for t in cats.transactions if t.description == description)


# --- categories -------------------------------------------------------------------------------------------------


def test_same_row_categorizes_differently(snapshot, packs):
    grocery, fashion = packs
    assert _category_of(snapshot, grocery, "ACH PAYMENT GARMENTS") == UNCATEGORIZED
    assert _category_of(snapshot, fashion, "ACH PAYMENT GARMENTS") == "apparel_stock"
    assert _category_of(snapshot, grocery, "REFUND MIDI DRESS") == UNCATEGORIZED
    assert _category_of(snapshot, fashion, "REFUND MIDI DRESS") == "customer_refunds"
    assert _category_of(snapshot, grocery, "ACH PAYMENT RICE") == "staples_wholesale"
    assert _category_of(snapshot, fashion, "ACH PAYMENT RICE") == UNCATEGORIZED


@pytest.mark.parametrize("pack_id", [GROCERY, FASHION])
def test_internal_transfers_never_count_as_revenue(snapshot, pack_id):
    df = frame(snapshot, load_pack(pack_id))
    moves = df[df["description"].str.contains("SETTLEMENT TO BANK|PAYNEST SETTLEMENT|CASH DEPOSIT")]
    assert len(moves) == 4 * 180 and set(moves["category"]) == {"internal_transfer"}
    assert set(moves["kind"]) == {"transfer"}
    sales = df[(df["kind"] == "revenue") & (df["amount_minor"] > 0) & (df["category"] != "customer_invoice")]
    daily_revenue = sales.groupby("date")
    assert set(daily_revenue["amount_minor"].sum()) == {DAILY_SALES}


@pytest.mark.parametrize("pack_id", [GROCERY, FASHION])
def test_scheduled_categories_match_the_seed_schedule(snapshot, pack_id):
    pack = load_pack(pack_id)
    for cid in ("rent", "payroll", "utilities", "insurance", "software_subscriptions", "customer_invoice"):
        assert pack.categories[cid].scheduled, cid
    assert pack.categories["customer_invoice"].kind == "revenue"
    assert _category_of(snapshot, pack, "SHIELDWELL INSURANCE PREMIUM") == "insurance"  # not "emi" in premium
    assert _category_of(snapshot, pack, "TRANSFER FROM SUNRISE CAFE REF AR-001") == "customer_invoice"


def test_categorize_does_not_mutate_the_snapshot(snapshot, packs):
    categorize_snapshot(snapshot, packs[1])
    assert all(t.category is None for t in snapshot.transactions)


def test_uncategorized_rows_are_neither_revenue_nor_cost(snapshot, packs):
    df = frame(snapshot, packs[0])
    assert set(df.loc[df["category"] == UNCATEGORIZED, "kind"]) == {UNCATEGORIZED}


# --- seasonality ------------------------------------------------------------------------------------------------


def test_seasonality_inputs_to_the_forecast_differ(packs):
    calendar = [{"id": "major_festival", "name": "Harvest Festival", "start": date(2026, 10, 25),
                 "end": date(2026, 10, 26)}]
    g, f = (build_engine_pack(p.engine_doc(), calendar) for p in packs)
    festival, december = date(2026, 10, 26), date(2026, 12, 15)
    assert g.multiplier(festival) == pytest.approx(1.02 * 1.90)
    assert f.multiplier(festival) == pytest.approx(1.15 * 2.30)
    assert g.multiplier(december) != f.multiplier(december)


# --- KPIs and benchmarks ----------------------------------------------------------------------------------------


def test_kpi_set_and_values_differ(snapshot, packs):
    g, f = ({k.id: k for k in compute_kpis(snapshot, p, CLOCK)} for p in packs)
    assert g["kpi.spoilage_share"].value == 0.0  # no disposal paid, real stock bought: a true zero
    assert "kpi.refund_share" in f and "kpi.refund_share" not in g
    assert g["kpi.gross_margin"].value != f["kpi.gross_margin"].value  # cogs differ by pack
    # Refunds over net revenue: sales plus three monthly customer-invoice payments in the window, minus refunds.
    refunds = 9_000 * 90
    assert f["kpi.refund_share"].value == pytest.approx(refunds / (DAILY_SALES * 90 + 3 * 50_000 - refunds))


def test_fashion_refunds_net_against_revenue(snapshot, packs):
    df = frame(snapshot, packs[1])
    refunds = df[df["category"] == "customer_refunds"]
    assert set(refunds["kind"]) == {"revenue"} and (refunds["amount_minor"] < 0).all()


def test_kpi_facts_trace_to_ledger_rows(snapshot, packs):
    ids = {t.id for t in snapshot.transactions}
    for pack in packs:
        for fact in compute_kpis(snapshot, pack, CLOCK):
            assert fact.source_row_ids and set(fact.source_row_ids) <= ids


def test_same_value_benchmarks_differently(packs):
    margin = Fact(id="kpi.gross_margin", value=0.40, unit="ratio", display="40.0%", source_row_ids=("t1",),
                  computed_by="test")
    buffer = Fact(id="buffer_days", value=20.0, unit="days", display="20 days", source_row_ids=("t1",),
                  computed_by="test")
    status = [{b.kpi_id: b.status for b in benchmark({"gross_margin": margin, "buffer_days": buffer}, p)[0]}
              for p in packs]
    assert status[0]["gross_margin"] == "above" and status[1]["gross_margin"] == "below"
    assert status[0]["buffer_days"] == "within" and status[1]["buffer_days"] == "below"
    assert status[0]["payment_fee_share"] == "no_data"


def test_benchmark_bounds_are_facts_from_the_pack(packs):
    results, bounds = benchmark({}, packs[0])
    by_id = {b.id: b for b in bounds}
    gm = next(r for r in results if r.kpi_id == "gross_margin")
    assert by_id[gm.healthy_min_fact_id].value == 0.18
    assert by_id[gm.healthy_min_fact_id].source_row_ids == ("pack:grocery_retail@1#kpis.gross_margin.healthy",)
    assert all(r.synthetic for r in results)


# --- leak detectors ---------------------------------------------------------------------------------------------


def _leaks(snapshot, pack) -> dict[str, list[Fact]]:
    """Yearly-impact fact of each finding, by detector."""
    out: dict[str, list[Fact]] = {}
    for finding in find_leaks(snapshot, pack, CLOCK):
        out.setdefault(finding.detector, []).append(finding.impact)
    return out


def test_leak_findings_differ(snapshot, packs):
    g, f = (_leaks(snapshot, p) for p in packs)
    assert "payment_fees" in g and "payment_fees" not in f  # 1.8% fees: above grocery max, under fashion max
    assert "refunds_excess" in f and "refunds_excess" not in g  # only fashion runs this detector
    assert set(g) == {"duplicate_subscription", "payment_fees", "late_fees"}
    assert set(f) == {"duplicate_subscription", "refunds_excess", "late_fees"}


def test_duplicate_subscription_catches_a_second_account_with_the_same_vendor(packs):
    rows = []
    for month in (6, 7, 8, 9, 10):
        rows.append((date(2026, month, 3), -5_900, "ShelfPOS", "SHELFPOS PRO SUBSCRIPTION ACCT SP-1", "direct_debit"))
        if month >= 7:
            rows.append((date(2026, month, 17), -5_900, "ShelfPOS", "SHELFPOS PRO SUBSCRIPTION ACCT SP-2",
                         "direct_debit"))
    rows.append((date(2026, 10, 1), 1_000, "Wallet customer", "PAYMENT RECEIVED", "wallet"))
    for pack in packs:
        [finding] = find_leaks(snapshot_of(rows), pack, CLOCK)
        fact = finding.impact
        assert fact.id.startswith("leak.duplicate_subscription.") and fact.value == 5_900 * 12


def test_one_month_of_double_billing_is_not_a_leak(packs):
    rows = [(date(2026, 10, 3), -5_900, "ShelfPOS", "SHELFPOS SUBSCRIPTION", "direct_debit"),
            (date(2026, 10, 17), -5_900, "ShelfPOS", "SHELFPOS SUBSCRIPTION", "direct_debit")]
    assert run_leak_detectors(snapshot_of(rows), packs[0], CLOCK) == []


def test_price_creep_detector_is_param_driven_on_unit_costs(snapshot, packs):
    from app.ledger.purchases import PurchaseLine

    spec = get_detector("supplier_price_creep")
    df = frame(snapshot, packs[0])
    lines = tuple(PurchaseLine(id=f"P{i}-L01", invoice_id=f"P{i}", supplier_id="sup_x", product_id="RICE",
                               invoice_date=date(2026, 5, 1) + timedelta(days=14 * i),
                               due_date=date(2026, 6, 1) + timedelta(days=14 * i), qty=10 + 5 * (i % 2),
                               unit_cost_minor=1000 + 20 * i, line_total_minor=(10 + 5 * (i % 2)) * (1000 + 20 * i))
                  for i in range(9))
    ctx = DetectorContext(pack=packs[0], today=TODAY, currency=CURRENCY, purchases=lines)
    [finding] = spec.fn(df, spec.params_model(min_increase=0.05), ctx)
    assert finding.subject == {"supplier_id": "sup_x", "product_id": "RICE"}
    assert set(finding.impact.source_row_ids) == {ln.id for ln in lines}
    assert spec.fn(df, spec.params_model(min_increase=0.9), ctx) == []


def test_duplicate_subscription_flags_the_cheaper_vendor(snapshot, packs):
    for pack in packs:
        [fact] = _leaks(snapshot, pack)["duplicate_subscription"]
        assert fact.value == POS_CHEAP_MONTHLY * 12  # the cheaper of the two monthly charges, for a year
        assert fact.unit == "money" and fact.currency == CURRENCY


def test_leak_facts_are_money_traced_to_rows(snapshot, packs):
    ids = {t.id for t in snapshot.transactions}
    for pack in packs:
        for finding in find_leaks(snapshot, pack, CLOCK):
            fact = finding.impact
            assert fact.id == f"{finding.id}.yearly_impact"
            assert isinstance(fact.value, int) and fact.value > 0
            assert fact.currency == CURRENCY and set(fact.source_row_ids) <= ids
            assert fact.computed_by.startswith("packs.detectors.")
            for detail in finding.details:
                assert detail.id.startswith(finding.id + ".") and detail.computed_by == fact.computed_by


def test_detectors_are_deterministic(snapshot, packs):
    for pack in packs:
        assert run_leak_detectors(snapshot, pack, CLOCK) == run_leak_detectors(snapshot, pack, CLOCK)


# --- financing fit and readiness --------------------------------------------------------------------------------


def test_financing_fit_differs(packs):
    g, f = packs
    types = ["merchant_cash_advance", "equipment_lease"]
    assert rank_product_types(g, types) == ["equipment_lease", "merchant_cash_advance"]
    assert rank_product_types(f, types) == ["merchant_cash_advance", "equipment_lease"]
    assert financing_fit(g, "inventory_financing").fit != financing_fit(f, "inventory_financing").fit


def _raw(name: str, value: float, unit: str) -> Fact:
    return Fact(id=f"raw.{name}", value=value, unit=unit, display=str(value), source_row_ids=("t1",),
                computed_by="test")


def test_same_raw_factors_score_differently():
    raw = {
        "inflow_regularity": _raw("inflow_regularity", 0.8, "ratio"),
        "revenue_stability": _raw("revenue_stability", 0.7, "ratio"),
        "buffer_days": _raw("buffer_days", 25.0, "days"),
        "collection_days": _raw("collection_days", 10.0, "days"),
        "payment_punctuality": _raw("payment_punctuality", 0.9, "ratio"),
    }
    g, f = (readiness_score(raw, load_pack(p)) for p in (GROCERY, FASHION))
    assert g.score.value == pytest.approx(0.7657, abs=1e-4)
    assert f.score.value == pytest.approx(0.6907, abs=1e-4)
    assert (g.band_id, f.band_id) == ("ready", "building")
    assert g.factor_scores["buffer_days"].value == pytest.approx((25 - 3) / (30 - 3))
    assert f.factor_scores["buffer_days"].value == pytest.approx((25 - 10) / (60 - 10))
    assert g.score.inputs == tuple(fs.id for fs in g.factor_scores.values())
    assert g.factor_scores["buffer_days"].inputs == ("raw.buffer_days",)


def test_readiness_needs_every_factor(packs):
    with pytest.raises(ValueError, match="needs raw facts"):
        readiness_score({}, packs[0])
