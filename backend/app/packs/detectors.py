"""Built-in leak detectors, registered by name for packs to reference.

Each detector is pure: (categorized ledger, params, context) -> list[Finding]. A Finding's impact Fact is the
estimated yearly impact in minor units and its source_row_ids are the evidence rows (invariant 4): ledger
transactions, purchase lines or sale lines. Detail Facts (unit costs, counts, rates) sit under the same ID prefix
so the owner and the planner can cite them too. Detectors only read; acting on a leak goes through propose_action
and the gateway like everything else.

Annualizing: a total seen over `span` days is scaled by 365 / span, where span runs from the first evidence day
in the lookback window to today (so a young business is not penalized for a window it has no history for).
"""

import statistics
from collections import defaultdict
from collections.abc import Iterable
from datetime import date, timedelta

import pandas as pd
from pydantic import Field

from app.engine.ads import campaigns, roas_fact
from app.engine.common import a_date, count, days, money, ratio, slug
from app.firewall.fact import Fact
from app.ledger.money import format_minor
from app.ledger.pos import SaleLine
from app.ledger.purchases import PurchaseLine
from app.packs.registry import DetectorContext, DetectorParams, Finding, detector
from app.packs.schema import Keyword, Ratio, Slug

YEAR_DAYS = 365
MIN_SPAN_DAYS = 28


def _window(df: pd.DataFrame, ctx: DetectorContext, lookback_days: int) -> pd.DataFrame:
    end = pd.Timestamp(ctx.today)
    start = end - timedelta(days=lookback_days)
    return df[(df["date"] > start) & (df["date"] <= end)]


def _since(ctx: DetectorContext, lookback_days: int) -> date:
    return ctx.today - timedelta(days=lookback_days)


def _annualize(total_minor: float, span_days: int) -> int:
    return round(total_minor * YEAR_DAYS / max(span_days, MIN_SPAN_DAYS))


def _span(ctx: DetectorContext, first: date) -> int:
    return (ctx.today - first).days


def _contains_any(series: pd.Series, keywords: tuple[str, ...]) -> pd.Series:
    low = series.str.lower()
    hit = pd.Series(False, index=series.index)
    for k in keywords:
        hit |= low.str.contains(k, regex=False)
    return hit


def _finding(name: str, key: str, ctx: DetectorContext, yearly_minor: int, rows: Iterable[str],
             subject: dict[str, str] | None = None, details: Iterable[Fact] = ()) -> Finding:
    """One finding: yearly impact (money, minor units) with its evidence rows, plus detail facts."""
    impact = Fact(
        id=f"leak.{name}.{key}.yearly_impact",
        value=int(yearly_minor),
        unit="money",
        currency=ctx.currency,
        display=f"{format_minor(int(yearly_minor), ctx.currency)} per year",
        source_row_ids=tuple(sorted({str(r) for r in rows})),
        computed_by=f"packs.detectors.{name}",
    )
    return Finding(detector=name, key=key, subject=dict(subject or {}), impact=impact, details=tuple(details))


def _prefix(name: str, key: str) -> str:
    return f"leak.{name}.{key}"


# --- duplicate_subscription -------------------------------------------------------------------------------------


class DuplicateSubscriptionParams(DetectorParams):
    categories: tuple[Slug, ...] = Field(min_length=1)
    groups: dict[Slug, tuple[Keyword, ...]] = Field(min_length=1)  # purpose -> keywords, e.g. pos: [pos]
    lookback_days: int = Field(default=120, ge=60, le=365)
    min_months: int = Field(default=2, ge=2)  # months with more than one charge before it counts as a leak


@detector("duplicate_subscription", DuplicateSubscriptionParams)
def duplicate_subscription(df: pd.DataFrame, p: DuplicateSubscriptionParams, ctx: DetectorContext) -> list[Finding]:
    """Paying more than once a month for the same purpose: a second account with the same vendor, or two vendors.

    Per calendar month and purpose group, the costliest charge is the one to keep; the rest are redundant. Found
    when that recurs in at least `min_months` months. Yearly impact = median redundant monthly amount x 12.
    Pack categories hold monthly subscriptions only, so a weekly-billed service never lands here.
    """
    name = "duplicate_subscription"
    w = _window(df, ctx, p.lookback_days)
    w = w[(w["amount_minor"] < 0) & w["category"].isin(p.categories)]
    found = []
    for group, keywords in sorted(p.groups.items()):
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
        monthly = round(statistics.median(redundant.values()))
        evidence = list(g.loc[months.isin(list(redundant)), "row_id"])
        key, by = slug(group), f"packs.detectors.{name}"
        found.append(_finding(name, key, ctx, monthly * 12, evidence, {"group": group}, [
            money(f"{_prefix(name, key)}.monthly", monthly, ctx.currency, by, evidence),
            count(f"{_prefix(name, key)}.months", len(redundant), by, evidence),
        ]))
    return found


# --- supplier_price_creep ---------------------------------------------------------------------------------------


class SupplierPriceCreepParams(DetectorParams):
    lookback_days: int = Field(default=365, ge=60, le=365)
    min_purchases: int = Field(default=6, ge=3)
    min_increase: Ratio = 0.05


@detector("supplier_price_creep", SupplierPriceCreepParams)
def supplier_price_creep(df: pd.DataFrame, p: SupplierPriceCreepParams, ctx: DetectorContext) -> list[Finding]:
    """A supplier's unit cost for one product rising: the last purchase line vs. the first in the window.

    Works on unit costs from purchase lines, so bigger seasonal orders never look like price rises. To count, the
    rise must hold up: the median of the last third of lines must also beat the first third's by `min_increase`
    (a one-off spike is not creep). Yearly impact = (latest - first unit cost) x units bought per year: what the
    business now pays extra at its current volume.
    """
    name, by = "supplier_price_creep", "packs.detectors.supplier_price_creep"
    since = _since(ctx, p.lookback_days)
    groups: dict[tuple[str, str], list[PurchaseLine]] = defaultdict(list)
    for line in ctx.purchases:
        if since < line.invoice_date <= ctx.today:
            groups[(line.supplier_id, line.product_id)].append(line)
    found = []
    for (supplier, product), lines in sorted(groups.items()):
        if len(lines) < p.min_purchases:
            continue
        lines.sort(key=lambda ln: (ln.invoice_date, ln.id))
        first, last = lines[0], lines[-1]
        third = len(lines) // 3
        early = statistics.median(ln.unit_cost_minor for ln in lines[:third])
        late = statistics.median(ln.unit_cost_minor for ln in lines[-third:])
        if first.unit_cost_minor <= 0 or early <= 0:
            continue
        change = last.unit_cost_minor / first.unit_cost_minor - 1
        if change < p.min_increase or late / early - 1 < p.min_increase:
            continue
        ids = [ln.id for ln in lines]
        qty = sum(ln.qty for ln in lines)
        yearly = _annualize((last.unit_cost_minor - first.unit_cost_minor) * qty, _span(ctx, first.invoice_date))
        key = slug(f"{supplier}-{product}")
        pre = _prefix(name, key)
        found.append(_finding(name, key, ctx, yearly, ids, {"supplier_id": supplier, "product_id": product}, [
            money(f"{pre}.first_unit_cost", first.unit_cost_minor, ctx.currency, by, [first.id]),
            money(f"{pre}.latest_unit_cost", last.unit_cost_minor, ctx.currency, by, [last.id]),
            a_date(f"{pre}.first_date", first.invoice_date, by, [first.id]),
            a_date(f"{pre}.latest_date", last.invoice_date, by, [last.id]),
            ratio(f"{pre}.increase", change, by, [first.id, last.id]),
            count(f"{pre}.purchases", len(lines), by, ids),
        ]))
    return found


# --- payment_fees -----------------------------------------------------------------------------------------------


class PaymentFeesParams(DetectorParams):
    fee_categories: tuple[Slug, ...] = Field(min_length=1)
    lookback_days: int = Field(default=90, ge=30, le=365)
    max_share_of_digital: Ratio


@detector("payment_fees", PaymentFeesParams)
def payment_fees(df: pd.DataFrame, p: PaymentFeesParams, ctx: DetectorContext) -> list[Finding]:
    """Payment fees above the pack's healthy share of digital inflows. Impact is the excess over that share."""
    name, by = "payment_fees", "packs.detectors.payment_fees"
    w = _window(df, ctx, p.lookback_days)
    digital_ids = {cid for cid, c in ctx.pack.categories.items() if c.digital}
    digital_rows = w[(w["amount_minor"] > 0) & w["category"].isin(digital_ids)]
    digital = digital_rows["amount_minor"].sum()
    fees = w[(w["amount_minor"] < 0) & w["category"].isin(p.fee_categories)]
    if digital <= 0 or fees.empty:
        return []
    total = -fees["amount_minor"].sum()
    excess = total - p.max_share_of_digital * digital
    if excess <= 0:
        return []
    ids = list(fees["row_id"])
    pre = _prefix(name, "all")
    return [_finding(name, "all", ctx, _annualize(excess, p.lookback_days), ids, {}, [
        money(f"{pre}.fees", int(total), ctx.currency, by, ids),
        ratio(f"{pre}.fee_share", total / digital, by, ids + list(digital_rows["row_id"])),
        ratio(f"{pre}.healthy_share", p.max_share_of_digital, by, [f"{ctx.pack.ref}#leak_detectors.{name}"]),
        days(f"{pre}.lookback", p.lookback_days, by, [f"{ctx.pack.ref}#leak_detectors.{name}"]),
    ])]


# --- late_fees --------------------------------------------------------------------------------------------------


class LateFeesParams(DetectorParams):
    keywords: tuple[Keyword, ...] = Field(min_length=1)
    lookback_days: int = Field(default=180, ge=30, le=365)


@detector("late_fees", LateFeesParams)
def late_fees(df: pd.DataFrame, p: LateFeesParams, ctx: DetectorContext) -> list[Finding]:
    """Late-payment fees and penalties the business paid. All of it is avoidable."""
    name, by = "late_fees", "packs.detectors.late_fees"
    w = _window(df, ctx, p.lookback_days)
    hits = w[(w["amount_minor"] < 0) & _contains_any(w["description"], p.keywords)]
    if hits.empty:
        return []
    ids, total = list(hits["row_id"]), int(-hits["amount_minor"].sum())
    pre = _prefix(name, "all")
    return [_finding(name, "all", ctx, _annualize(total, p.lookback_days), ids, {}, [
        money(f"{pre}.paid", total, ctx.currency, by, ids),
        count(f"{pre}.charges", len(ids), by, ids),
    ])]


# --- refunds_excess ---------------------------------------------------------------------------------------------


class RefundsExcessParams(DetectorParams):
    refund_categories: tuple[Slug, ...] = Field(min_length=1)
    lookback_days: int = Field(default=90, ge=30, le=365)
    max_share_of_revenue: Ratio


@detector("refunds_excess", RefundsExcessParams)
def refunds_excess(df: pd.DataFrame, p: RefundsExcessParams, ctx: DetectorContext) -> list[Finding]:
    """Customer refunds/returns above the pack's healthy share of revenue. Impact is the excess."""
    name, by = "refunds_excess", "packs.detectors.refunds_excess"
    w = _window(df, ctx, p.lookback_days)
    revenue = w.loc[(w["amount_minor"] > 0) & (w["kind"] == "revenue"), "amount_minor"].sum()
    refunds = w[(w["amount_minor"] < 0) & w["category"].isin(p.refund_categories)]
    if revenue <= 0 or refunds.empty:
        return []
    total = -refunds["amount_minor"].sum()
    excess = total - p.max_share_of_revenue * revenue
    if excess <= 0:
        return []
    ids = list(refunds["row_id"])
    return [_finding(name, "all", ctx, _annualize(excess, p.lookback_days), ids, {}, [
        money(f"{_prefix(name, 'all')}.refunds", int(total), ctx.currency, by, ids),
    ])]


# --- unprofitable_products --------------------------------------------------------------------------------------


class UnprofitableProductsParams(DetectorParams):
    lookback_days: int = Field(default=180, ge=30, le=365)
    min_sale_days: int = Field(default=14, ge=1)  # ignore a product sold on only a handful of days


@detector("unprofitable_products", UnprofitableProductsParams)
def unprofitable_products(df: pd.DataFrame, p: UnprofitableProductsParams, ctx: DetectorContext) -> list[Finding]:
    """Products whose point-of-sale revenue is below their supplier cost. Impact is the yearly loss on them.

    Sale-line cost is the supplier unit cost on the day of sale, so a product pushed under water by price creep
    shows up here too.
    """
    name, by = "unprofitable_products", "packs.detectors.unprofitable_products"
    since = _since(ctx, p.lookback_days)
    lines: dict[str, list[SaleLine]] = defaultdict(list)
    for s in ctx.sale_lines:
        if since < s.date <= ctx.today:
            lines[s.product_id].append(s)
    found = []
    for product, ss in sorted(lines.items()):
        if len({s.date for s in ss}) < p.min_sale_days:
            continue
        revenue, cost = sum(s.revenue_minor for s in ss), sum(s.cost_minor for s in ss)
        if revenue - cost >= 0:
            continue
        ids = [s.id for s in ss]
        first = min(s.date for s in ss)
        key = slug(product)
        pre = _prefix(name, key)
        found.append(_finding(name, key, ctx, _annualize(cost - revenue, _span(ctx, first)), ids,
                              {"product_id": product}, [
            money(f"{pre}.revenue", revenue, ctx.currency, by, ids),
            money(f"{pre}.cost", cost, ctx.currency, by, ids),
            money(f"{pre}.gross_profit", revenue - cost, ctx.currency, by, ids),
            ratio(f"{pre}.margin", (revenue - cost) / revenue if revenue else None, by, ids),
            a_date(f"{pre}.since", first, by, ids),
        ]))
    return found


# --- missed_early_pay_discounts ---------------------------------------------------------------------------------


class MissedEarlyPayParams(DetectorParams):
    lookback_days: int = Field(default=365, ge=30, le=365)
    min_invoices: int = Field(default=2, ge=1)


@detector("missed_early_pay_discounts", MissedEarlyPayParams)
def missed_early_pay_discounts(df: pd.DataFrame, p: MissedEarlyPayParams, ctx: DetectorContext) -> list[Finding]:
    """Supplier invoices that offered a discount for paying by a deadline, paid after it. One finding per supplier.

    Missed amount per invoice = invoice total x discount rate. Only paid invoices count: an unpaid invoice whose
    deadline has not passed is still an opportunity, not a loss.
    """
    name, by = "missed_early_pay_discounts", "packs.detectors.missed_early_pay_discounts"
    since = _since(ctx, p.lookback_days)
    invoices: dict[str, list[PurchaseLine]] = defaultdict(list)
    for line in ctx.purchases:
        if since < line.invoice_date <= ctx.today:
            invoices[line.invoice_id].append(line)
    by_supplier: dict[str, list[list[PurchaseLine]]] = defaultdict(list)
    for _, lines in sorted(invoices.items()):
        head = lines[0]
        if (head.early_pay_discount_pct > 0 and head.discount_deadline and head.paid_on
                and ctx.today >= head.paid_on > head.discount_deadline):
            by_supplier[head.supplier_id].append(lines)
    found = []
    for supplier, missed in sorted(by_supplier.items()):
        if len(missed) < p.min_invoices:
            continue
        total = sum(round(sum(ln.line_total_minor for ln in inv) * inv[0].early_pay_discount_pct) for inv in missed)
        ids = [ln.id for inv in missed for ln in inv]
        first = min(inv[0].invoice_date for inv in missed)
        rates = sorted({inv[0].early_pay_discount_pct for inv in missed})
        key = slug(supplier)
        pre = _prefix(name, key)
        found.append(_finding(name, key, ctx, _annualize(total, _span(ctx, first)), ids, {"supplier_id": supplier}, [
            money(f"{pre}.missed", total, ctx.currency, by, ids),
            count(f"{pre}.invoices", len(missed), by, ids),
            ratio(f"{pre}.discount_rate", rates[-1], by, ids),
        ]))
    return found


# --- slow_moving_stock ------------------------------------------------------------------------------------------


class SlowMovingStockParams(DetectorParams):
    min_days_held: int = Field(default=90, ge=14, le=365)
    max_sell_through: Ratio = 0.5  # sold / bought at or below this counts as slow
    carrying_cost_rate: Ratio = 0.25  # yearly cost of holding stock (space, capital, markdowns), synthetic


@detector("slow_moving_stock", SlowMovingStockParams)
def slow_moving_stock(df: pd.DataFrame, p: SlowMovingStockParams, ctx: DetectorContext) -> list[Finding]:
    """Stock bought at least `min_days_held` ago that has mostly not sold. Impact = stock value x carrying rate.

    Units on hand = units bought - units sold, from purchase lines and sale lines up to today. Valued at the latest
    unit cost paid.
    """
    name, by = "slow_moving_stock", "packs.detectors.slow_moving_stock"
    bought: dict[str, list[PurchaseLine]] = defaultdict(list)
    for line in ctx.purchases:
        if line.invoice_date <= ctx.today:
            bought[line.product_id].append(line)
    sold: dict[str, list[SaleLine]] = defaultdict(list)
    for s in ctx.sale_lines:
        if s.date <= ctx.today:
            sold[s.product_id].append(s)
    found = []
    for product, lines in sorted(bought.items()):
        first = min(ln.invoice_date for ln in lines)
        if (ctx.today - first).days < p.min_days_held:
            continue
        units_in = sum(ln.qty for ln in lines)
        units_out = sum(s.qty for s in sold.get(product, []))
        on_hand = units_in - units_out
        if on_hand <= 0 or units_out / units_in > p.max_sell_through:
            continue
        latest = max(lines, key=lambda ln: (ln.invoice_date, ln.id))
        value = on_hand * latest.unit_cost_minor
        ids = [ln.id for ln in lines] + [s.id for s in sold.get(product, [])]
        key = slug(product)
        pre = _prefix(name, key)
        found.append(_finding(name, key, ctx, round(value * p.carrying_cost_rate), ids, {"product_id": product}, [
            money(f"{pre}.stock_value", value, ctx.currency, by, ids),
            count(f"{pre}.units_on_hand", on_hand, by, ids),
            count(f"{pre}.units_bought", units_in, by, [ln.id for ln in lines]),
            ratio(f"{pre}.sell_through", units_out / units_in, by, ids),
            days(f"{pre}.days_held", (ctx.today - first).days, by, [lines[0].id, "clock:today"]),
        ]))
    return found


# --- losing_ad_campaigns ----------------------------------------------------------------------------------------


class LosingAdCampaignsParams(DetectorParams):
    lookback_days: int = Field(default=90, ge=28, le=365)
    min_roas: float = Field(default=1.0, gt=0, le=10)  # below this the campaign costs more than it brings in


@detector("losing_ad_campaigns", LosingAdCampaignsParams)
def losing_ad_campaigns(df: pd.DataFrame, p: LosingAdCampaignsParams, ctx: DetectorContext) -> list[Finding]:
    """Ad campaigns whose attributed sales are below their spend (return on ad spend under `min_roas`).

    Yearly impact = (spend - attributed sales) over the window, annualized. A campaign without attributed sales is
    not judged: its return is unknown, not zero. Reads the business's own ad spend export (ledger/records.py).
    """
    name, by = "losing_ad_campaigns", "packs.detectors.losing_ad_campaigns"
    found = []
    for c in campaigns(ctx.ad_spend, ctx.today, p.lookback_days):
        if c.roas is None or c.roas >= p.min_roas:
            continue
        ids = list(c.row_ids)
        first = min(a.date for a in ctx.ad_spend if a.id in set(ids))
        key = slug(c.id)
        pre = _prefix(name, key)
        found.append(_finding(name, key, ctx, _annualize(c.spend_minor - (c.sales_minor or 0), _span(ctx, first)),
                              ids, {"campaign": c.name, "channel": c.channel}, [
            money(f"{pre}.spend", c.spend_minor, ctx.currency, by, ids),
            money(f"{pre}.attributed_sales", c.sales_minor or 0, ctx.currency, by, ids),
            roas_fact(f"{pre}.roas", c.roas, ids).model_copy(update={"computed_by": by}),
        ]))
    return found


# --- product_returns --------------------------------------------------------------------------------------------


class ProductReturnsParams(DetectorParams):
    lookback_days: int = Field(default=90, ge=28, le=365)
    max_return_rate: Ratio = 0.15  # returned units / sold units above this counts as a leak
    min_units_sold: int = Field(default=20, ge=1)


@detector("product_returns", ProductReturnsParams)
def product_returns(df: pd.DataFrame, p: ProductReturnsParams, ctx: DetectorContext) -> list[Finding]:
    """Products that come back too often: returned units (negative qty sale lines) / units sold above
    `max_return_rate`. Impact = yearly revenue refunded on that product (from the return lines themselves)."""
    name, by = "product_returns", "packs.detectors.product_returns"
    since = _since(ctx, p.lookback_days)
    lines: dict[str, list[SaleLine]] = defaultdict(list)
    for s in ctx.sale_lines:
        if since < s.date <= ctx.today:
            lines[s.product_id].append(s)
    found = []
    for product, ss in sorted(lines.items()):
        sold = sum(s.qty for s in ss if s.qty > 0)
        returns = [s for s in ss if s.qty < 0]
        returned = -sum(s.qty for s in returns)
        if sold < p.min_units_sold or not returns or returned / sold <= p.max_return_rate:
            continue
        refunded = -sum(s.revenue_minor for s in returns)
        ids = [s.id for s in ss]
        first = min(s.date for s in ss)
        key = slug(product)
        pre = _prefix(name, key)
        found.append(_finding(name, key, ctx, _annualize(refunded, _span(ctx, first)), [s.id for s in returns],
                              {"product_id": product}, [
            ratio(f"{pre}.return_rate", returned / sold, by, ids),
            count(f"{pre}.returned", returned, by, [s.id for s in returns]),
            count(f"{pre}.sold", sold, by, [s.id for s in ss if s.qty > 0]),
            money(f"{pre}.refunded", refunded, ctx.currency, by, [s.id for s in returns]),
            ratio(f"{pre}.healthy_rate", p.max_return_rate, by, [f"{ctx.pack.ref}#leak_detectors.{name}"]),
        ]))
    return found
