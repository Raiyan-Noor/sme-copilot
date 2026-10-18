"""Built-in leak detectors, registered by name for packs to reference.

Each detector is pure: (categorized ledger, params, context) -> list[Fact]. Each finding is one Fact whose value is
the estimated yearly impact in minor units and whose source_row_ids are the evidence rows (invariant 4). Detectors
only read the ledger; acting on a leak goes through propose_action and the gateway like everything else.

Not here yet (build prompt 14; register under these names, which the seed manifest expects): unprofitable_products,
missed_early_pay_discounts and slow_moving_stock, plus supplier_price_creep rebuilt on unit costs. They need the
purchase lines and sale lines the seed writes (purchases.csv, sale_lines.csv), which the ledger snapshot does not
carry yet.
"""

import hashlib
import statistics
from datetime import timedelta

import pandas as pd
from pydantic import Field

from app.firewall.fact import Fact
from app.ledger.money import format_minor
from app.packs.registry import DetectorContext, DetectorParams, detector
from app.packs.schema import Keyword, Ratio, Slug

YEAR_DAYS = 365


def _window(df: pd.DataFrame, ctx: DetectorContext, lookback_days: int) -> pd.DataFrame:
    end = pd.Timestamp(ctx.today)
    start = end - timedelta(days=lookback_days)
    return df[(df["date"] > start) & (df["date"] <= end)]


def _annualize(total_minor: float, lookback_days: int) -> int:
    return round(total_minor * YEAR_DAYS / lookback_days)


def _contains_any(series: pd.Series, keywords: tuple[str, ...]) -> pd.Series:
    low = series.str.lower()
    hit = pd.Series(False, index=series.index)
    for k in keywords:
        hit |= low.str.contains(k, regex=False)
    return hit


def _leak_fact(name: str, ctx: DetectorContext, yearly_minor: int, rows: pd.Series) -> Fact:
    """One finding: estimated yearly impact (money, minor units) with its evidence rows."""
    row_ids = tuple(sorted(rows.astype(str)))
    digest = hashlib.sha256(",".join(row_ids).encode()).hexdigest()[:8]
    return Fact(
        id=f"leak.{name}.{digest}",
        value=yearly_minor,
        unit="money",
        currency=ctx.currency,
        display=f"{format_minor(yearly_minor, ctx.currency)} per year",
        source_row_ids=row_ids,
        computed_by=f"packs.detectors.{name}",
    )


# --- duplicate_subscription -------------------------------------------------------------------------------------


class DuplicateSubscriptionParams(DetectorParams):
    categories: tuple[Slug, ...] = Field(min_length=1)
    groups: dict[Slug, tuple[Keyword, ...]] = Field(min_length=1)  # purpose -> keywords, e.g. pos: [pos]
    lookback_days: int = Field(default=120, ge=60, le=365)
    min_months: int = Field(default=2, ge=2)  # months with more than one charge before it counts as a leak


@detector("duplicate_subscription", DuplicateSubscriptionParams)
def duplicate_subscription(df: pd.DataFrame, p: DuplicateSubscriptionParams, ctx: DetectorContext) -> list[Fact]:
    """Paying more than once a month for the same purpose: a second account with the same vendor, or two vendors.

    Per calendar month and purpose group, the costliest charge is the one to keep; the rest are redundant. Found
    when that recurs in at least `min_months` months. Yearly impact = median redundant monthly amount x 12.
    Pack categories hold monthly subscriptions only, so a weekly-billed service never lands here.
    """
    w = _window(df, ctx, p.lookback_days)
    w = w[(w["amount_minor"] < 0) & w["category"].isin(p.categories)]
    facts = []
    for _, keywords in sorted(p.groups.items()):
        g = w[_contains_any(w["counterparty"], keywords) | _contains_any(w["description"], keywords)]
        if g.empty:
            continue
        months = g["date"].dt.to_period("M")
        redundant: dict[pd.Period, int] = {}
        for month, rows in g.groupby(months):
            charges = sorted(-rows["amount_minor"], reverse=True)
            if len(charges) > 1:
                redundant[month] = sum(charges[1:])
        if len(redundant) < p.min_months:
            continue
        monthly = statistics.median(redundant.values())
        evidence = g.loc[months.isin(list(redundant)), "row_id"]
        facts.append(_leak_fact("duplicate_subscription", ctx, round(monthly * 12), evidence))
    return facts


# --- supplier_price_creep ---------------------------------------------------------------------------------------


class SupplierPriceCreepParams(DetectorParams):
    categories: tuple[Slug, ...] = Field(min_length=1)
    lookback_days: int = Field(default=180, ge=60, le=365)
    min_purchases: int = Field(default=6, ge=3)
    min_increase: Ratio = 0.05


@detector("supplier_price_creep", SupplierPriceCreepParams)
def supplier_price_creep(df: pd.DataFrame, p: SupplierPriceCreepParams, ctx: DetectorContext) -> list[Fact]:
    """Average purchase from one supplier rising steadily: last third of purchases vs. first third.

    Works on amounts per purchase, so seasonal order sizes look like price changes. Not enabled in the bundled
    packs until build prompt 14 adds unit costs from purchase lines.
    """
    w = _window(df, ctx, p.lookback_days)
    w = w[(w["amount_minor"] < 0) & w["category"].isin(p.categories)]
    facts = []
    for _, g in sorted(w.groupby("counterparty"), key=lambda kv: kv[0]):
        if len(g) < p.min_purchases:
            continue
        g = g.sort_values(["date", "row_id"])
        third = len(g) // 3
        base = -g["amount_minor"].iloc[:third].mean()
        recent = -g["amount_minor"].iloc[-third:].mean()
        if base <= 0 or recent / base - 1 < p.min_increase:
            continue
        purchases_per_year = len(g) * YEAR_DAYS / p.lookback_days
        yearly = round((recent - base) * purchases_per_year)
        facts.append(_leak_fact("supplier_price_creep", ctx, yearly, g["row_id"]))
    return facts


# --- payment_fees -----------------------------------------------------------------------------------------------


class PaymentFeesParams(DetectorParams):
    fee_categories: tuple[Slug, ...] = Field(min_length=1)
    lookback_days: int = Field(default=90, ge=30, le=365)
    max_share_of_digital: Ratio


@detector("payment_fees", PaymentFeesParams)
def payment_fees(df: pd.DataFrame, p: PaymentFeesParams, ctx: DetectorContext) -> list[Fact]:
    """Payment fees above the pack's healthy share of digital inflows. Impact is the excess over that share."""
    w = _window(df, ctx, p.lookback_days)
    digital_ids = {cid for cid, c in ctx.pack.categories.items() if c.digital}
    digital = w.loc[(w["amount_minor"] > 0) & w["category"].isin(digital_ids), "amount_minor"].sum()
    fees = w[(w["amount_minor"] < 0) & w["category"].isin(p.fee_categories)]
    if digital <= 0 or fees.empty:
        return []
    excess = -fees["amount_minor"].sum() - p.max_share_of_digital * digital
    if excess <= 0:
        return []
    return [_leak_fact("payment_fees", ctx, _annualize(excess, p.lookback_days), fees["row_id"])]


# --- late_fees --------------------------------------------------------------------------------------------------


class LateFeesParams(DetectorParams):
    keywords: tuple[Keyword, ...] = Field(min_length=1)
    lookback_days: int = Field(default=180, ge=30, le=365)


@detector("late_fees", LateFeesParams)
def late_fees(df: pd.DataFrame, p: LateFeesParams, ctx: DetectorContext) -> list[Fact]:
    """Late-payment fees and penalties the business paid. All of it is avoidable."""
    w = _window(df, ctx, p.lookback_days)
    hits = w[(w["amount_minor"] < 0) & _contains_any(w["description"], p.keywords)]
    if hits.empty:
        return []
    return [_leak_fact("late_fees", ctx, _annualize(-hits["amount_minor"].sum(), p.lookback_days), hits["row_id"])]


# --- refunds_excess ---------------------------------------------------------------------------------------------


class RefundsExcessParams(DetectorParams):
    refund_categories: tuple[Slug, ...] = Field(min_length=1)
    lookback_days: int = Field(default=90, ge=30, le=365)
    max_share_of_revenue: Ratio


@detector("refunds_excess", RefundsExcessParams)
def refunds_excess(df: pd.DataFrame, p: RefundsExcessParams, ctx: DetectorContext) -> list[Fact]:
    """Customer refunds/returns above the pack's healthy share of revenue. Impact is the excess."""
    w = _window(df, ctx, p.lookback_days)
    revenue = w.loc[(w["amount_minor"] > 0) & (w["kind"] == "revenue"), "amount_minor"].sum()
    refunds = w[(w["amount_minor"] < 0) & w["category"].isin(p.refund_categories)]
    if revenue <= 0 or refunds.empty:
        return []
    excess = -refunds["amount_minor"].sum() - p.max_share_of_revenue * revenue
    if excess <= 0:
        return []
    return [_leak_fact("refunds_excess", ctx, _annualize(excess, p.lookback_days), refunds["row_id"])]
