"""Financing match and repayment-safe sizing. Pure: (snapshot, pack, clock, catalog, facts) -> results + Facts.

Three steps, each producing Facts with traces (invariant 4):

1. Metrics (`financing.metric.*`): months of bank history, months of unbroken digital sales history, digital and
   invoice shares of sales and average monthly sales over the last 90 complete days. Rules also read
   `readiness.score`, `cash.buffer_days` and the raw Passport factors, which the caller computed first.
2. Capacity (`financing.capacity.*`), the most a business can safely repay per month under a stressed forecast:
       expected monthly net    = (forecast.90d.end_balance - cash.balance) / 3
       stress loss per month   = revenue_drop * forecast.90d.inflows / 3 * gross margin   (stock bought falls with
                                 sales, so lost cash is the lost gross profit; no margin known: the whole drop)
       stressed monthly surplus = expected monthly net - stress loss
       surplus cap             = max_share_of_stressed_surplus * stressed surplus   (the rest is a cushion)
       liquidity cap           = lowest bad-case balance over the forecast / liquidity_horizon_months, so paying
                                 the installments due inside the forecast never takes the bad case below zero
       max installment         = max(0, min(surplus cap, liquidity cap))
3. Per product: every rule passes or fails with a reason, and the offer is sized so its installment fits the max
   installment. `capped_by` says whether repayment safety or the product's own maximum set the size. A product
   whose safe size is below its minimum is `not_safe`, even when every rule passes.

The lender makes the credit decision. This module only says which products the business meets the published rules
for and how much it can safely repay; it never applies (that is the T3 action submit_loan_application).
"""

import math
from collections.abc import Mapping
from datetime import date, timedelta
from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.clock import Clock
from app.engine.catalog import RULES, Catalog, Product, Rule
from app.engine.common import CLOCK_SOURCE, a_date, days, in_window, money, ratio, window
from app.engine.readiness_factors import add_months, is_revenue, months_between
from app.firewall.fact import Fact
from app.ledger.snapshot import LedgerSnapshot
from app.packs.financing import financing_fit
from app.packs.schema import Pack

BY_METRIC = "engine.financing.metrics"
BY_CAPACITY = "engine.financing.capacity"
BY_MATCH = "engine.financing.match"
SHARE_WINDOW_DAYS = 90
DIGITAL_GAP_DAYS = 31  # a month with no digital sales restarts the digital history
FORECAST_MONTHS = 3  # the forecast horizon (90 days) in months

Status = Literal["eligible", "not_eligible", "not_safe"]
FitLevel = Literal["strong", "moderate", "weak"]


class RuleResult(BaseModel):
    """One rule. `reason` is code-written text with `{fact:<id>}` placeholders and no digits outside them."""

    model_config = ConfigDict(frozen=True)

    rule: str
    label: str
    op: Literal[">=", "<="]
    passed: bool
    metric_fact_id: str
    threshold_fact_id: str
    eligible_from_fact_id: str | None = None
    reason: str


class ProductMatch(BaseModel):
    model_config = ConfigDict(frozen=True)

    product_id: str
    name: str
    lender: str
    type: str
    fit: FitLevel
    fit_reason: str
    status: Status
    eligible: bool
    capped_by: Literal["repayment_safety", "product_max"] | None
    rules: list[RuleResult]
    min_amount_fact_id: str
    max_amount_fact_id: str
    safe_amount_fact_id: str
    installment_fact_id: str
    total_cost_fact_id: str
    term_fact_id: str
    monthly_rate_fact_id: str


class FinancingMatch(BaseModel):
    model_config = ConfigDict(frozen=True)

    catalog_ref: str
    synthetic: Literal[True] = True
    max_installment_fact_id: str
    capacity_fact_ids: list[str]
    products: list[ProductMatch]  # eligible first, then best pack fit, then catalog order


# Metrics --------------------------------------------------------------------------------------------------------

def _months_fact(fid: str, n: int, by: str, sources=(), inputs=()) -> Fact:
    return Fact(id=fid, value=int(n), unit="count", display="1 month" if n == 1 else f"{n} months",
                source_row_ids=tuple(sorted(set(sources))), inputs=tuple(inputs), computed_by=by)


def _digital_run_start(snapshot: LedgerSnapshot, pack: Pack, today: date) -> tuple[date, str] | None:
    """(first day, first row ID) of the current unbroken run of digital sales, or None if there is none."""
    rows = [t for t in snapshot.transactions
            if t.posted_on < today and t.amount_minor > 0 and is_revenue(t, pack)
            and pack.categories[t.category].digital]
    if not rows or (today - rows[-1].posted_on).days > DIGITAL_GAP_DAYS:
        return None
    start = rows[0]
    for prev, cur in zip(rows, rows[1:]):
        if (cur.posted_on - prev.posted_on).days > DIGITAL_GAP_DAYS:
            start = cur
    return start.posted_on, start.id


def financing_metrics(snapshot: LedgerSnapshot, pack: Pack, clock: Clock) -> list[Fact]:
    today = clock.today()
    cur = snapshot.currency
    facts: list[Fact] = []

    past = [t for t in snapshot.transactions if t.posted_on < today]
    if past:
        first = past[0]
        facts += [a_date("financing.metric.history_start", first.posted_on, BY_METRIC, [first.id]),
                  _months_fact("financing.metric.history_months", months_between(first.posted_on, today), BY_METRIC,
                               [first.id, CLOCK_SOURCE])]
    else:
        facts.append(_months_fact("financing.metric.history_months", 0, BY_METRIC, [CLOCK_SOURCE]))

    run = _digital_run_start(snapshot, pack, today)
    if run:
        facts += [a_date("financing.metric.digital_history_start", run[0], BY_METRIC, [run[1]]),
                  _months_fact("financing.metric.digital_history_months", months_between(run[0], today), BY_METRIC,
                               [run[1], CLOCK_SOURCE])]
    else:
        facts.append(_months_fact("financing.metric.digital_history_months", 0, BY_METRIC, [CLOCK_SOURCE]))

    start, end = window(today, SHARE_WINDOW_DAYS)
    rows = [t for t in in_window(snapshot, start, end) if is_revenue(t, pack)]
    revenue = sum(t.amount_minor for t in rows)
    digital = [t for t in rows if pack.categories[t.category].digital]
    invoiced = [t for t in rows if pack.categories[t.category].scheduled]
    ids = [t.id for t in rows] or [CLOCK_SOURCE]
    rev_id = f"financing.metric.revenue.last_{SHARE_WINDOW_DAYS}d"

    def share(part: list) -> float | None:
        return sum(t.amount_minor for t in part) / revenue if revenue > 0 else None

    facts += [
        money(rev_id, revenue, cur, BY_METRIC, ids),
        money("financing.metric.avg_monthly_revenue", round(revenue * 30 / SHARE_WINDOW_DAYS), cur, BY_METRIC,
              inputs=[rev_id]),
        ratio("financing.metric.digital_share", share(digital), BY_METRIC, [t.id for t in digital], inputs=[rev_id]),
        ratio("financing.metric.invoice_revenue_share", share(invoiced), BY_METRIC, [t.id for t in invoiced],
              inputs=[rev_id]),
    ]
    return facts


# Capacity -------------------------------------------------------------------------------------------------------

_DAILY_LOW = "forecast.daily."


def repayment_capacity(facts: Mapping[str, Fact], catalog: Catalog, currency: str) -> list[Fact]:
    """`financing.capacity.*` from forecast and margin facts the caller already computed."""
    s = catalog.sizing
    balance = facts["cash.balance"].value
    end, inflows = facts["forecast.90d.end_balance"].value, facts["forecast.90d.inflows"].value
    margin_fact = facts.get("margin.last_90d.gross_margin")
    margin = margin_fact.value if margin_fact and isinstance(margin_fact.value, float) else None
    margin = min(1.0, max(0.0, margin)) if margin is not None else 1.0
    lows = [(f.value, f.id) for fid, f in facts.items()
            if fid.startswith(_DAILY_LOW) and fid.endswith(".low") and isinstance(f.value, int)]
    lowest, lowest_id = min(lows) if lows else (balance, "cash.balance")

    expected = round((end - balance) / FORECAST_MONTHS)
    loss = round(s.revenue_drop * inflows / FORECAST_MONTHS * margin)
    surplus = expected - loss
    surplus_cap = math.floor(max(0, surplus) * s.max_share_of_stressed_surplus)
    liquidity_cap = math.floor(max(0, lowest) / s.liquidity_horizon_months)
    max_installment = max(0, min(surplus_cap, liquidity_cap))
    cat = [f"{catalog.ref}#sizing"]
    margin_in = [margin_fact.id] if margin_fact else []
    p = "financing.capacity"
    return [
        money(f"{p}.expected_monthly_net", expected, currency, BY_CAPACITY,
              inputs=["cash.balance", "forecast.90d.end_balance"]),
        ratio(f"{p}.revenue_drop", s.revenue_drop, BY_CAPACITY, cat),
        money(f"{p}.stress_loss", loss, currency, BY_CAPACITY, cat,
              inputs=["forecast.90d.inflows", f"{p}.revenue_drop", *margin_in]),
        money(f"{p}.stressed_monthly_surplus", surplus, currency, BY_CAPACITY,
              inputs=[f"{p}.expected_monthly_net", f"{p}.stress_loss"]),
        money(f"{p}.surplus_cap", surplus_cap, currency, BY_CAPACITY, cat, inputs=[f"{p}.stressed_monthly_surplus"]),
        money(f"{p}.lowest_bad_case_balance", lowest, currency, BY_CAPACITY, inputs=[lowest_id]),
        money(f"{p}.liquidity_cap", liquidity_cap, currency, BY_CAPACITY, cat,
              inputs=[f"{p}.lowest_bad_case_balance"]),
        money(f"{p}.max_installment", max_installment, currency, BY_CAPACITY,
              inputs=[f"{p}.surplus_cap", f"{p}.liquidity_cap"]),
    ]


def installment(principal: int, rate: float, months: int) -> int:
    """Level monthly installment in minor units, rounded up."""
    if principal <= 0:
        return 0
    if rate == 0:
        return math.ceil(principal / months)
    return math.ceil(principal * rate / (1 - (1 + rate) ** -months))


def safe_principal(max_installment: int, product: Product) -> int:
    """The largest principal, on the product's step and at most its maximum, whose installment fits."""
    r, n = product.monthly_rate, product.term_months
    raw = max_installment * n if r == 0 else max_installment * (1 - (1 + r) ** -n) / r
    p = min(product.max_amount_minor, math.floor(raw / product.step_minor) * product.step_minor)
    while p > 0 and installment(p, r, n) > max_installment:
        p -= product.step_minor
    return max(0, p)


# Matching -------------------------------------------------------------------------------------------------------

def _threshold(fid: str, rule: Rule, product: Product, currency: str, catalog: Catalog) -> Fact:
    src = [f"{catalog.ref}#{product.id}.rules.{rule.rule}"]
    unit = rule.spec.unit
    if unit == "count":
        return _months_fact(fid, int(rule.value), BY_MATCH, src)
    if unit == "money":
        return money(fid, int(rule.value), currency, BY_MATCH, src)
    if unit == "days":
        return days(fid, rule.value, BY_MATCH, src)
    return ratio(fid, rule.value, BY_MATCH, src)


def _check(rule: Rule, metric: Fact | None, threshold: Fact) -> bool:
    if metric is None or not isinstance(metric.value, int | float):
        return False
    return metric.value >= threshold.value if rule.spec.op == ">=" else metric.value <= threshold.value


_HISTORY_START = {"min_history_months": "financing.metric.history_start",
                  "min_digital_history_months": "financing.metric.digital_history_start"}


def _rule(product: Product, rule: Rule, facts: Mapping[str, Fact], today: date, currency: str,
          catalog: Catalog) -> tuple[RuleResult, list[Fact]]:
    spec = RULES[rule.rule]
    pre = f"financing.{product.id}.rule.{rule.rule}"
    threshold = _threshold(f"{pre}.threshold", rule, product, currency, catalog)
    metric = facts.get(spec.metric)
    passed = _check(rule, metric, threshold)
    out = [threshold]
    eligible_from = None
    word = "minimum" if spec.op == ">=" else "maximum"
    if metric is None:
        reason = f"{spec.label}: not available for this business, needs {{fact:{threshold.id}}}"
    elif passed:
        reason = f"{spec.label}: {{fact:{metric.id}}} meets the {word} of {{fact:{threshold.id}}}"
    else:
        side = "below the minimum" if spec.op == ">=" else "above the maximum"
        reason = f"{spec.label}: {{fact:{metric.id}}} is {side} of {{fact:{threshold.id}}}"
        start = facts.get(_HISTORY_START.get(rule.rule, ""))
        if start is not None and isinstance(start.value, date):
            when = max(add_months(start.value, int(rule.value)), today + timedelta(days=1))
            eligible_from = f"{pre}.eligible_from"
            out.append(a_date(eligible_from, when, BY_MATCH, inputs=[start.id, threshold.id]))
            reason += f"; met from {{fact:{eligible_from}}} if trading continues"
    return RuleResult(rule=rule.rule, label=spec.label, op=spec.op, passed=passed,
                      metric_fact_id=spec.metric, threshold_fact_id=threshold.id,
                      eligible_from_fact_id=eligible_from, reason=reason), out


def _fit_level(fit: float) -> FitLevel:
    return "strong" if fit >= 0.7 else "moderate" if fit >= 0.4 else "weak"


def match_product(product: Product, facts: Mapping[str, Fact], pack: Pack, clock: Clock, catalog: Catalog,
                  currency: str) -> tuple[ProductMatch, list[Fact]]:
    today = clock.today()
    pre = f"financing.{product.id}"
    cat = [f"{catalog.ref}#{product.id}"]
    out: list[Fact] = [
        money(f"{pre}.min_amount", product.min_amount_minor, currency, BY_MATCH, cat),
        money(f"{pre}.max_amount", product.max_amount_minor, currency, BY_MATCH, cat),
        _months_fact(f"{pre}.term", product.term_months, BY_MATCH, cat),
        ratio(f"{pre}.monthly_rate", product.monthly_rate, BY_MATCH, cat),
    ]
    results = []
    for rule in product.rules:
        result, rule_facts = _rule(product, rule, facts, today, currency, catalog)
        results.append(result)
        out += rule_facts
    eligible = all(r.passed for r in results)

    cap = facts["financing.capacity.max_installment"]
    safe = safe_principal(cap.value, product)
    status: Status = "not_eligible" if not eligible else "eligible" if safe >= product.min_amount_minor \
        else "not_safe"
    if safe < product.min_amount_minor:
        safe = 0
    pay = installment(safe, product.monthly_rate, product.term_months)
    sizing_inputs = [cap.id, f"{pre}.max_amount", f"{pre}.min_amount", f"{pre}.term", f"{pre}.monthly_rate"]
    out += [
        money(f"{pre}.safe_amount", safe, currency, BY_MATCH, inputs=sizing_inputs),
        money(f"{pre}.installment", pay, currency, BY_MATCH, inputs=[f"{pre}.safe_amount", f"{pre}.term",
                                                                      f"{pre}.monthly_rate"]),
        money(f"{pre}.total_cost", pay * product.term_months - safe if safe else 0, currency, BY_MATCH,
              inputs=[f"{pre}.installment", f"{pre}.safe_amount", f"{pre}.term"]),
    ]
    capped_by = None
    if status == "eligible":
        capped_by = "product_max" if safe >= product.max_amount_minor else "repayment_safety"
    fit = financing_fit(pack, product.type)
    return ProductMatch(
        product_id=product.id, name=product.name, lender=product.lender, type=product.type,
        fit=_fit_level(fit.fit), fit_reason=fit.reason, status=status, eligible=eligible, capped_by=capped_by,
        rules=results, min_amount_fact_id=f"{pre}.min_amount", max_amount_fact_id=f"{pre}.max_amount",
        safe_amount_fact_id=f"{pre}.safe_amount", installment_fact_id=f"{pre}.installment",
        total_cost_fact_id=f"{pre}.total_cost", term_fact_id=f"{pre}.term",
        monthly_rate_fact_id=f"{pre}.monthly_rate",
    ), out


def match_financing(facts: Mapping[str, Fact], pack: Pack, clock: Clock, catalog: Catalog,
                    currency: str) -> tuple[FinancingMatch, list[Fact]]:
    """Match every catalog product. `facts` must hold the metric, readiness, cash, forecast and margin facts.

    A catalog in another currency than the business matches nothing: every product is reported not eligible.
    """
    capacity = repayment_capacity(facts, catalog, currency)
    pool = {**facts, **{f.id: f for f in capacity}}
    out = list(capacity)
    matches: list[ProductMatch] = []
    for product in catalog.products:
        m, product_facts = match_product(product, pool, pack, clock, catalog, currency)
        if catalog.currency != currency:
            m = m.model_copy(update={"status": "not_eligible", "eligible": False, "capped_by": None})
        matches.append(m)
        out += product_facts
    order = {p.id: i for i, p in enumerate(catalog.products)}
    rank = {"eligible": 0, "not_safe": 1, "not_eligible": 2}
    matches.sort(key=lambda m: (rank[m.status], -financing_fit(pack, m.type).fit, order[m.product_id]))
    return FinancingMatch(catalog_ref=catalog.ref, max_installment_fact_id="financing.capacity.max_installment",
                          capacity_fact_ids=[f.id for f in capacity], products=matches), out
