"""Ad advisor: per-product ad performance, a ranked "worth promoting" list, and a budget what-if calculator.

Pure: (products, sale lines, ad spend lines, clock) -> (Facts, AdAdvisorInsights). Builds on engine/ads.py
(campaign ROAS over a trailing window) and the same margin formula as engine/margins.py, so a product's profit
after ad spend is its margin on the ads' attributed sales minus what was spent reaching them. A product only gets
ad metrics when its ad spend export links a campaign row to it (`AdSpendLine.product_id`); unlinked campaign spend
stays in engine/ads.py's channel-level view. Every number cites the ad spend and sale lines it summed (invariant 4).

Exclusion reasons (thresholds come from the Skill Pack's `losing_ad_campaigns` and `product_returns` detector
params, so one pack file tunes both the leak finder and the advisor):
- `low_stock_cover`: fewer days of stock on hand than the pack's stockout threshold. Restock before advertising.
- `negative_profit_after_ads`: the product's margin on attributed sales does not cover what was spent reaching it,
  even when raw return on ad spend looks fine (a thin-margin product can lose money on ads above 1.0x ROAS).
- `high_return_rate`: returned units above the pack's healthy return rate eat into what the ads bring in.

The what-if calculator estimates the change in gross profit from moving ad budget between two campaigns, using
each campaign's historical return over a short and a longer window as a low/high range (the same bad/good-case
idea as engine/forecast.py), capped at `cap_multiplier` times the destination campaign's historical spend so a
small campaign's past return is never extrapolated to an unrealistic budget.
"""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import timedelta

from app.clock import Clock
from app.engine.ads import Campaign, campaigns, roas_fact
from app.engine.common import money, ratio, slug, window
from app.firewall.fact import Fact
from app.ledger.pos import Product, SaleLine
from app.ledger.records import AdSpendLine
from app.packs.schema import Pack

BY = "engine.ad_advisor.product_ad_performance"
WHATIF_BY = "engine.ad_advisor.ad_budget_what_if"
AD_WINDOW_DAYS = 90
MARGIN_WINDOW_DAYS = 90
TREND_DAYS = 30
STOCKOUT_DAYS = 14
DEFAULT_MAX_RETURN_RATE = 0.15
DEFAULT_MIN_ROAS = 1.0
WHATIF_RECENT_DAYS = 30
WHATIF_LONGER_DAYS = 90
WHATIF_CAP_MULTIPLIER = 1.5


@dataclass(frozen=True)
class ProductAdPerformance:
    product_id: str
    spend_fact: str | None = None
    attributed_sales_fact: str | None = None
    roas_fact: str | None = None
    profit_after_ads_fact: str | None = None
    return_rate_fact: str | None = None
    units_trend: str = "unknown"  # "up" | "down" | "flat" | "unknown"
    cover_days: float | None = None  # not a Fact here: product_facts() already emits the owner-facing one
    excluded: tuple[str, ...] = ()  # "low_stock_cover" | "negative_profit_after_ads" | "high_return_rate"


@dataclass(frozen=True)
class AdAdvisorInsights:
    by_product: dict[str, ProductAdPerformance] = field(default_factory=dict)
    ranked: tuple[str, ...] = ()  # worth-promoting product IDs, best profit-after-ads first


def _pack_param(pack: Pack | None, detector: str, key: str, default: float) -> float:
    if pack is None:
        return default
    cfg = next((d for d in pack.leak_detectors if d.detector == detector), None)
    return float(cfg.params[key]) if cfg and key in cfg.params else default


def _units_sold(lines: list[SaleLine], start, end) -> int:
    return sum(s.qty for s in lines if start <= s.date <= end and s.qty > 0)


def _trend(now_units: int, prior_units: int) -> str:
    if prior_units == 0:
        return "up" if now_units > 0 else "unknown"
    change = (now_units - prior_units) / prior_units
    return "up" if change > 0.1 else "down" if change < -0.1 else "flat"


def product_ad_performance(
    products: tuple[Product, ...], sale_lines: tuple[SaleLine, ...], ad_spend: tuple[AdSpendLine, ...],
    clock: Clock, currency: str, pack: Pack | None = None, ad_window_days: int = AD_WINDOW_DAYS,
    margin_window_days: int = MARGIN_WINDOW_DAYS, trend_days: int = TREND_DAYS, stockout_days: int = STOCKOUT_DAYS,
) -> tuple[list[Fact], AdAdvisorInsights]:
    today = clock.today()
    since_ads = today - timedelta(days=ad_window_days)
    linked = [a for a in ad_spend if a.product_id and since_ads < a.date <= today]
    if not linked:
        return [], AdAdvisorInsights()

    by_product_ads: dict[str, list[AdSpendLine]] = defaultdict(list)
    for a in linked:
        by_product_ads[a.product_id].append(a)
    by_product_sales: dict[str, list[SaleLine]] = defaultdict(list)
    for s in sale_lines:
        by_product_sales[s.product_id].append(s)
    products_by_id = {p.id: p for p in products}
    margin_start, margin_end = window(today, margin_window_days)
    max_return_rate = _pack_param(pack, "product_returns", "max_return_rate", DEFAULT_MAX_RETURN_RATE)

    facts: list[Fact] = []
    by_product: dict[str, ProductAdPerformance] = {}
    profit_minor: dict[str, int] = {}
    for pid, lines in sorted(by_product_ads.items()):
        pre, ids = f"ads.product.{slug(pid)}", [a.id for a in lines]
        spend = sum(a.spend_minor for a in lines)
        facts.append(money(f"{pre}.spend", spend, currency, BY, ids))
        spend_fid = f"{pre}.spend"

        has_sales = any(a.attributed_sales_minor is not None for a in lines)
        sales = sum(a.attributed_sales_minor or 0 for a in lines) if has_sales else None
        sales_fid = roas_fid = None
        if sales is not None:
            facts.append(money(f"{pre}.attributed_sales", sales, currency, BY, ids))
            sales_fid = f"{pre}.attributed_sales"
            facts.append(roas_fact(f"{pre}.roas", sales / spend if spend else None, ids))
            roas_fid = f"{pre}.roas"

        product_sales = by_product_sales.get(pid, [])
        window_sales = [s for s in product_sales if margin_start <= s.date <= margin_end]
        revenue = sum(s.revenue_minor for s in window_sales)
        margin = (revenue - sum(s.cost_minor for s in window_sales)) / revenue if revenue > 0 else None

        profit_fid, profit = None, None
        if sales is not None and margin is not None:
            profit = round(sales * margin) - spend
            facts.append(money(f"{pre}.profit_after_ad_spend", profit, currency, BY,
                               ids + [s.id for s in window_sales], inputs=[spend_fid, sales_fid]))
            profit_fid = f"{pre}.profit_after_ad_spend"
            profit_minor[pid] = profit

        sold = sum(s.qty for s in window_sales if s.qty > 0)
        returns = [s for s in window_sales if s.qty < 0]
        returned = -sum(s.qty for s in returns)
        return_rate, return_fid = None, None
        if sold > 0 and returns:
            return_rate = returned / sold
            facts.append(ratio(f"{pre}.return_rate", return_rate, BY, [s.id for s in returns]))
            return_fid = f"{pre}.return_rate"

        trend_now_start, trend_now_end = today - timedelta(days=trend_days), today - timedelta(days=1)
        trend_prior_end = trend_now_start - timedelta(days=1)
        trend_prior_start = trend_prior_end - timedelta(days=trend_days - 1)
        trend = _trend(_units_sold(product_sales, trend_now_start, trend_now_end),
                       _units_sold(product_sales, trend_prior_start, trend_prior_end))

        product = products_by_id.get(pid)
        cover = None
        if product and product.stock is not None and sold > 0:
            cover = product.stock / (sold / margin_window_days)

        reasons = []
        if cover is not None and cover < stockout_days:
            reasons.append("low_stock_cover")
        if profit is not None and profit < 0:
            reasons.append("negative_profit_after_ads")
        if return_rate is not None and return_rate > max_return_rate:
            reasons.append("high_return_rate")

        by_product[pid] = ProductAdPerformance(
            product_id=pid, spend_fact=spend_fid, attributed_sales_fact=sales_fid, roas_fact=roas_fid,
            profit_after_ads_fact=profit_fid, return_rate_fact=return_fid, units_trend=trend, cover_days=cover,
            excluded=tuple(reasons))

    ranked = tuple(sorted((pid for pid in profit_minor if not by_product[pid].excluded),
                         key=lambda pid: (-profit_minor[pid], pid)))
    return facts, AdAdvisorInsights(by_product=by_product, ranked=ranked)


@dataclass(frozen=True)
class WhatIfResult:
    from_campaign_id: str
    to_campaign_id: str
    capped: bool
    amount_requested_fact: str
    amount_applied_fact: str
    roas_from_fact: str
    roas_to_fact: str
    profit_delta_low_fact: str
    profit_delta_high_fact: str


def ad_budget_what_if(
    ad_spend: tuple[AdSpendLine, ...], clock: Clock, currency: str, from_campaign_id: str, to_campaign_id: str,
    amount_minor: int, margin: float, recent_days: int = WHATIF_RECENT_DAYS, longer_days: int = WHATIF_LONGER_DAYS,
    cap_multiplier: float = WHATIF_CAP_MULTIPLIER,
) -> tuple[list[Fact], WhatIfResult] | None:
    """Estimated change in gross profit from moving `amount_minor` from one campaign to another, as a low/high
    range built from each campaign's return over a recent and a longer window. None if either campaign has no
    history with a known return in any window."""
    today = clock.today()
    estimates: list[tuple[int, Campaign, Campaign]] = []
    for days_back in sorted({recent_days, longer_days}):
        found = {c.id: c for c in campaigns(ad_spend, today, days_back)}
        frm, to = found.get(from_campaign_id), found.get(to_campaign_id)
        if frm is not None and to is not None and frm.roas is not None and to.roas is not None:
            estimates.append((days_back, frm, to))
    if not estimates:
        return None

    longest = max(estimates, key=lambda e: e[0])
    cap_minor = round(longest[2].spend_minor * cap_multiplier)
    applied = min(amount_minor, cap_minor) if cap_minor else amount_minor
    capped = applied < amount_minor

    deltas = [round((applied * to.roas - applied * frm.roas) * margin) for _, frm, to in estimates]
    low, high = min(deltas), max(deltas)
    key = f"ads.whatif.{slug(from_campaign_id)}.{slug(to_campaign_id)}"
    amt_key = f"{key}.amt{applied}"  # the amount actually used is part of the ID: a different amount is a
    # different estimate, and the same pair of campaigns may be asked about more than once in a conversation.
    _, longest_frm, longest_to = longest
    rows = list(longest_frm.row_ids) + list(longest_to.row_ids)
    facts = [
        roas_fact(f"{key}.roas_from", longest_frm.roas, list(longest_frm.row_ids)),
        roas_fact(f"{key}.roas_to", longest_to.roas, list(longest_to.row_ids)),
        money(f"{amt_key}.amount_applied", applied, currency, WHATIF_BY, rows),
        money(f"{amt_key}.profit_delta_low", low, currency, WHATIF_BY, rows),
        money(f"{amt_key}.profit_delta_high", high, currency, WHATIF_BY, rows),
    ]
    if capped:
        facts.append(money(f"{amt_key}.amount_requested", amount_minor, currency, WHATIF_BY, rows))
    return facts, WhatIfResult(
        from_campaign_id=from_campaign_id, to_campaign_id=to_campaign_id, capped=capped,
        amount_requested_fact=f"{amt_key}.amount_requested" if capped else f"{amt_key}.amount_applied",
        amount_applied_fact=f"{amt_key}.amount_applied", roas_from_fact=f"{key}.roas_from",
        roas_to_fact=f"{key}.roas_to", profit_delta_low_fact=f"{amt_key}.profit_delta_low",
        profit_delta_high_fact=f"{amt_key}.profit_delta_high")
