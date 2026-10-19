"""engine/ad_advisor.py: per-product ad performance, the worth-promoting ranking, exclusion reasons and the
budget what-if calculator. Pure functions with hand-built fixtures, no DB: same style as the engine's own unit
tests for a single calculator."""

from datetime import date, timedelta

import pytest

from app.clock import FixedClock
from app.engine.ad_advisor import ad_budget_what_if, product_ad_performance
from app.ledger.pos import Product, SaleLine
from app.ledger.records import AdSpendLine

TODAY = date(2026, 10, 19)
CLOCK = FixedClock(TODAY)
CURRENCY = "USD"


def ad(day_offset: int, campaign_id: str, campaign: str, channel: str, spend: int, sales: int | None,
      product_id: str | None) -> AdSpendLine:
    d = TODAY - timedelta(days=day_offset)
    return AdSpendLine(id=f"AD-{campaign_id}-{day_offset}", date=d, campaign_id=campaign_id, campaign=campaign,
                      channel=channel, spend_minor=spend, attributed_sales_minor=sales, product_id=product_id)


def sale(day_offset: int, product_id: str, qty: int, revenue: int, cost: int) -> SaleLine:
    d = TODAY - timedelta(days=day_offset)
    return SaleLine(id=f"SL-{product_id}-{day_offset}-{qty}", date=d, product_id=product_id, qty=qty,
                    revenue_minor=revenue, cost_minor=cost)


# A product sold steadily all quarter at a 60% margin, plenty of stock, and a campaign that pays for itself well.
WINNER = Product(id="WINNER", name="Bestseller", price_minor=1000, cost_minor=400, stock=500)
# Almost out of stock: a strong campaign return, but advertising more would run it out.
LOW_STOCK = Product(id="LOWSTOCK", name="Almost Gone", price_minor=1000, cost_minor=400, stock=5)
# A thin-margin product: ROAS above 1 but the margin does not cover the ad spend.
THIN_MARGIN = Product(id="THIN", name="Thin Margin", price_minor=1000, cost_minor=750, stock=500)
PRODUCTS = (WINNER, LOW_STOCK, THIN_MARGIN)


def _weekly_sales(product_id: str, price: int, cost: int, units_per_week: int, weeks: int = 13) -> list[SaleLine]:
    return [sale(7 * w, product_id, units_per_week, units_per_week * price, units_per_week * cost)
           for w in range(weeks)]


def _weekly_ads(campaign_id: str, name: str, channel: str, spend: int, sales: int, product_id: str | None,
                weeks: int = 13) -> list[AdSpendLine]:
    return [ad(7 * w, campaign_id, name, channel, spend, sales, product_id) for w in range(weeks)]


SALE_LINES = tuple(
    _weekly_sales("WINNER", 1000, 400, 20) + _weekly_sales("LOWSTOCK", 1000, 400, 20)
    + _weekly_sales("THIN", 1000, 750, 20))

AD_LINES = tuple(
    _weekly_ads("winner-camp", "Winner Campaign", "Instagram", 5000, 15000, "WINNER")  # ROAS 3x, margin 60%
    + _weekly_ads("lowstock-camp", "Low Stock Campaign", "Instagram", 5000, 15000, "LOWSTOCK")  # same, low stock
    + _weekly_ads("thin-camp", "Thin Margin Campaign", "Facebook", 5000, 7500, "THIN")  # ROAS 1.5x, margin 25%
    + _weekly_ads("unlinked-camp", "Brand Awareness", "Google", 2000, None, None))  # no product, no sales data


@pytest.fixture(scope="module")
def performance():
    return product_ad_performance(PRODUCTS, SALE_LINES, AD_LINES, CLOCK, CURRENCY)


def test_clear_winner_is_ranked_first_and_not_excluded(performance):
    _, insights = performance
    assert insights.ranked[0] == "WINNER"
    assert insights.by_product["WINNER"].excluded == ()


def test_low_stock_product_is_excluded_despite_good_return(performance):
    _, insights = performance
    perf = insights.by_product["LOWSTOCK"]
    assert "low_stock_cover" in perf.excluded
    assert "LOWSTOCK" not in insights.ranked
    assert perf.cover_days is not None and perf.cover_days < 14


def test_thin_margin_product_loses_money_after_ads_despite_roas_above_one(performance):
    facts, insights = performance
    perf = insights.by_product["THIN"]
    assert "negative_profit_after_ads" in perf.excluded
    assert "THIN" not in insights.ranked
    profit = next(f for f in facts if f.id == perf.profit_after_ads_fact)
    assert profit.value < 0
    roas = next(f for f in facts if f.id == perf.roas_fact)
    assert roas.value > 1  # the trap: a healthy-looking ROAS that still loses money net of margin


def test_unlinked_campaign_spend_produces_no_product_entry(performance):
    _, insights = performance
    assert set(insights.by_product) == {"WINNER", "LOWSTOCK", "THIN"}


def test_every_fact_traces_to_ad_spend_or_sale_rows(performance):
    facts, _ = performance
    known = {a.id for a in AD_LINES} | {s.id for s in SALE_LINES}
    for f in facts:
        assert (set(f.source_row_ids) <= known) or f.inputs, f.id


def test_high_return_rate_is_excluded():
    # 12 complete weeks of WINNER sales in the margin window = 240 units; 40 returned is well above the 15%
    # healthy rate (packs.detectors.product_returns' default), without changing the margin or the ad numbers.
    returns = [sale(d, "WINNER", -10, -10000, -4000) for d in (1, 8, 15, 22)]
    facts, insights = product_ad_performance(
        PRODUCTS, SALE_LINES + tuple(returns), AD_LINES, CLOCK, CURRENCY)
    assert "high_return_rate" in insights.by_product["WINNER"].excluded


def test_determinism(performance):
    facts, insights = performance
    facts2, insights2 = product_ad_performance(PRODUCTS, SALE_LINES, AD_LINES, CLOCK, CURRENCY)
    assert facts == facts2
    assert insights.ranked == insights2.ranked


# --- ad_budget_what_if --------------------------------------------------------------------------------------------

WHATIF_ADS = tuple(
    _weekly_ads("losing", "Losing Campaign", "Facebook", 5000, 3000, None)  # ROAS 0.6
    + _weekly_ads("winning", "Winning Campaign", "Instagram", 4000, 12000, None))  # ROAS 3.0


def test_moving_budget_to_the_better_campaign_estimates_a_profit_gain():
    result = ad_budget_what_if(WHATIF_ADS, CLOCK, CURRENCY, "losing", "winning", 10_000, margin=0.5)
    assert result is not None
    facts, whatif = result
    low = next(f for f in facts if f.id == whatif.profit_delta_low_fact)
    high = next(f for f in facts if f.id == whatif.profit_delta_high_fact)
    assert low.value <= high.value
    assert low.value > 0  # moving to the campaign with the better historical return is a gain either way
    assert whatif.capped is False


def test_amount_is_capped_to_the_destination_campaigns_historical_spend():
    # 13 weeks at 4000/week = 52000 historical spend for "winning"; 1.5x that is the cap.
    result = ad_budget_what_if(WHATIF_ADS, CLOCK, CURRENCY, "losing", "winning", 1_000_000, margin=0.5)
    assert result is not None
    facts, whatif = result
    applied = next(f for f in facts if f.id == whatif.amount_applied_fact)
    assert whatif.capped is True
    assert applied.value < 1_000_000
    assert applied.value == pytest.approx(round(4000 * 13 * 1.5), rel=0.2)


def test_unknown_campaign_returns_none():
    assert ad_budget_what_if(WHATIF_ADS, CLOCK, CURRENCY, "losing", "nonexistent", 1000, margin=0.5) is None
