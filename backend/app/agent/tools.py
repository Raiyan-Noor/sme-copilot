"""The planner's read/compute tools (Tier 1) and the registry that also holds propose_action.

Invariant 4: a read tool returns numbers only as `{fact:<id>}` placeholders, registered in the turn's FactStore via
`TurnContext.cite`. Comparisons the planner needs to reason with ("below the healthy range", "shortfall likely",
"revenue down") are computed here in code and returned as enums, so the planner never sees a raw value.
Invariant 2: tools return IDs, enums, pack labels and the business's own counterparty names, never statement or
email text. Invariant 5: nothing here or in actions.py is a Tier 4 tool.

Every name here must match a Tier 1 pattern in policy.yaml (`get_*`, `list_*`, `explain_fact`, ...); a test checks.
"""

import calendar
import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.agent.ads_tools import (
    NoAdsArgs, ProductArgs, WhatIfArgs, ad_budget_what_if, product_performance, rank_products_for_ads,
)
from app.agent.context import TurnContext, safe_label
from app.agent.financing_tools import DraftArgs, NoFinancingArgs, get_loan_application_draft, get_passport, match_financing
from app.engine.common import slug
from app.engine.scheduled import scheduled_prefix
from app.firewall.explain import explain
from app.ledger.pii import TOKEN
from app.packs.leaks import detector_labels
from app.quarantine.facts import inbox_prefix
from app.services.finance import resolver


class ToolError(ValueError):
    """A bad call the planner can fix: returned to it as `{"error": ...}`, never raised to the owner."""


class NoArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    params: type[BaseModel]
    fn: Callable[[TurnContext, Any], dict[str, Any]]

    def schema(self) -> dict[str, Any]:
        """OpenAI function-tool definition."""
        return {"type": "function", "function": {
            "name": self.name, "description": self.description, "parameters": _clean(self.params.model_json_schema())}}


def _clean(node: Any) -> Any:
    if isinstance(node, dict):
        return {k: _clean(v) for k, v in node.items() if k != "title"}
    if isinstance(node, list):
        return [_clean(v) for v in node]
    return node


def _compact(d: dict[str, Any]) -> dict[str, Any]:
    """Drop fields whose fact the business does not have."""
    return {k: v for k, v in d.items() if v is not None and v != []}


def _benchmark(ctx: TurnContext, kpi_id: str):
    return next((b for b in ctx.computed.benchmarks if b.kpi_id == kpi_id), None)


# get_cash_position ----------------------------------------------------------------------------------------------

def get_cash_position(ctx: TurnContext, _: NoArgs) -> dict[str, Any]:
    buffer = _benchmark(ctx, "buffer_days")
    return _compact({
        "total_balance": ctx.cite("cash.balance", "Cash balance, all accounts"),
        "buffer_days": ctx.cite("cash.buffer_days", "Cash buffer"),
        "buffer_vs_healthy_range": buffer.status if buffer else "no_data",
        "healthy_buffer_min": ctx.cite(buffer.healthy_min_fact_id, "Healthy buffer, minimum")
        if buffer and buffer.healthy_min_fact_id else None,
        "average_daily_spend": ctx.cite("cash.avg_daily_spend.last_90d", "Average daily spending"),
        "last_ledger_activity": ctx.cite("cash.last_activity", "Last ledger activity"),
        "note": "Per-account balances are on the Cash flow screen.",
    })


# get_forecast ---------------------------------------------------------------------------------------------------

class ForecastArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    horizon: Literal["30d", "60d", "90d"] = Field("30d", description="How far ahead to look.")


_DAILY_LOW = re.compile(r"^forecast\.daily\.(\d{4}-\d{2}-\d{2})\.low$")


def _shortfall(ctx: TurnContext, horizon: str) -> str:
    min_balance = ctx.value(f"forecast.{horizon}.min_balance")
    if isinstance(min_balance, int) and min_balance < 0:
        return "expected"
    end = ctx.value(f"forecast.{horizon}.end_date")
    for fact_id, fact in ctx.pool.items():
        m = _DAILY_LOW.match(fact_id)
        if m and isinstance(fact.value, int) and fact.value < 0 and (end is None or date.fromisoformat(m[1]) <= end):
            return "possible_in_a_bad_case"
    return "none"


def get_forecast(ctx: TurnContext, a: ForecastArgs) -> dict[str, Any]:
    p = f"forecast.{a.horizon}"
    if not ctx.has(f"{p}.end_balance"):
        raise ToolError("no forecast is available for this business")
    return _compact({
        "horizon_end": ctx.cite(f"{p}.end_date", "Forecast end date"),
        "expected_end_balance": ctx.cite(f"{p}.end_balance", "Expected balance at the end"),
        "end_balance_bad_case": ctx.cite(f"{p}.end_balance_low", "End balance, bad case"),
        "end_balance_good_case": ctx.cite(f"{p}.end_balance_high", "End balance, good case"),
        "lowest_expected_balance": ctx.cite(f"{p}.min_balance", "Lowest expected balance"),
        "lowest_balance_date": ctx.cite(f"{p}.min_balance_date", "Date of the lowest balance"),
        "expected_inflows": ctx.cite(f"{p}.inflows", "Expected money in"),
        "expected_outflows": ctx.cite(f"{p}.outflows", "Expected money out"),
        "known_bills_due": ctx.cite(f"{p}.scheduled_out", "Known bills due"),
        "known_invoices_due_in": ctx.cite(f"{p}.scheduled_in", "Customer invoices due in"),
        "shortfall_risk": _shortfall(ctx, a.horizon),
        "overdue_customer_invoices": ctx.cite("forecast.overdue_receivables", "Overdue customer invoices"),
        "note": "Bad and good cases are a plausible range from past day-to-day swings, not a guarantee.",
    })


# get_runway -----------------------------------------------------------------------------------------------------

def get_runway(ctx: TurnContext, _: NoArgs) -> dict[str, Any]:
    if not ctx.has("runway.days"):
        raise ToolError("no runway is available for this business")
    runs_out = ctx.value("runway.date") is not None
    stressed_out = ctx.value("runway.stressed.date") is not None
    return _compact({
        "runway": ctx.cite("runway.days", "Runway"),
        "cash_runs_out_on": ctx.cite("runway.date", "Date cash runs out"),
        "runway_stressed": ctx.cite("runway.stressed.days", "Runway if sales drop"),
        "stressed_runs_out_on": ctx.cite("runway.stressed.date", "Date cash runs out if sales drop"),
        "status": "runs_out_within_forecast" if runs_out else "lasts_beyond_forecast",
        "stressed_status": "runs_out_within_forecast" if stressed_out else "lasts_beyond_forecast",
    })


# get_profit_and_loss --------------------------------------------------------------------------------------------

class PnlArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    period: Literal["month", "week"] = "month"
    periods_back: int = Field(0, ge=0, le=12, description="0 = the current period, 1 = the one before, ...")


_PNL_KEY = re.compile(r"^pnl\.(\d{4}-(?:w\d{2}|\d{2}))\.revenue$")


def _periods(ctx: TurnContext, period: str) -> list[str]:
    keys = [m[1] for m in map(_PNL_KEY.match, ctx.pool) if m]
    return sorted(k for k in keys if ("-w" in k) == (period == "week"))


def _complete(ctx: TurnContext, key: str, period: str) -> bool:
    covered = ctx.value(f"pnl.{key}.days_covered")
    if period == "week":
        return covered == 7
    year, month = map(int, key.split("-"))
    return covered == calendar.monthrange(year, month)[1]


def _direction(now: Any, before: Any) -> str:
    if not isinstance(now, int) or not isinstance(before, int) or before == 0:
        return "unknown"
    change = (now - before) / abs(before)
    return "up" if change > 0.02 else "down" if change < -0.02 else "flat"


def _lines(ctx: TurnContext, key: str, kind: str) -> list[dict[str, Any]]:
    categories = ctx.computed.inputs.pack.categories
    prefix = f"pnl.{key}.{kind}."
    out = []
    for fact_id in sorted(f for f in ctx.pool if f.startswith(prefix)):
        cat = fact_id[len(prefix):]
        spec = categories.get(cat)
        label = spec.label if spec else cat.replace("_", " ")
        out.append({"category": cat, "label": safe_label(label), "amount": ctx.cite(fact_id, label)})
    return out


def get_profit_and_loss(ctx: TurnContext, a: PnlArgs) -> dict[str, Any]:
    keys = _periods(ctx, a.period)
    if a.periods_back >= len(keys):
        raise ToolError(f"there is no {a.period} that far back in the ledger")
    idx = len(keys) - 1 - a.periods_back
    key = keys[idx]
    prev = keys[idx - 1] if idx > 0 else None
    p = f"pnl.{key}"
    complete = _complete(ctx, key, a.period)
    prev_complete = prev is not None and _complete(ctx, prev, a.period)
    return _compact({
        "period_start": ctx.cite(f"{p}.first_day", "Period start"),
        "period_end": ctx.cite(f"{p}.last_day", "Period end"),
        "days_covered": ctx.cite(f"{p}.days_covered", "Days covered"),
        "period_complete": complete,
        "revenue": ctx.cite(f"{p}.revenue", "Revenue"),
        "cost_of_goods": ctx.cite(f"{p}.cogs", "Cost of goods"),
        "gross_profit": ctx.cite(f"{p}.gross_profit", "Gross profit"),
        "gross_margin": ctx.cite(f"{p}.gross_margin", "Gross margin"),
        "operating_expenses": ctx.cite(f"{p}.operating_expenses", "Operating expenses"),
        "operating_profit": ctx.cite(f"{p}.operating_profit", "Operating profit"),
        "owner_drawings": ctx.cite(f"{p}.owner_drawings", "Owner drawings"),
        "revenue_lines": _lines(ctx, key, "revenue"),
        "expense_lines": _lines(ctx, key, "expense"),
        "previous_period_revenue": ctx.cite(f"pnl.{prev}.revenue", "Previous period revenue") if prev else None,
        "previous_period_operating_profit": ctx.cite(f"pnl.{prev}.operating_profit",
                                                     "Previous period operating profit") if prev else None,
        "revenue_vs_previous": _direction(ctx.value(f"{p}.revenue"), ctx.value(f"pnl.{prev}.revenue"))
        if prev else "no_previous_period",
        "comparison_note": None if complete and prev_complete
        else "At least one of the two periods is partial, so compare with care.",
        "basis": "Cash basis: money actually received and paid, days before today only.",
    })


# get_margins ----------------------------------------------------------------------------------------------------

_PRODUCT_MARGIN = re.compile(r"^margin\.product\.(.+)\.last_90d\.margin$")


def get_margins(ctx: TurnContext, _: NoArgs) -> dict[str, Any]:
    by_slug = {slug(p.id): p for p in ctx.computed.inputs.products}
    ranked = []
    for fact_id, fact in ctx.pool.items():
        m = _PRODUCT_MARGIN.match(fact_id)
        if m and isinstance(fact.value, float):
            ranked.append((fact.value, m[1]))
    ranked.sort()

    def product(product_slug: str) -> dict[str, Any]:
        p = by_slug.get(product_slug)
        name = p.name if p else product_slug
        prefix = f"margin.product.{product_slug}.last_90d"
        ctx.trust(p.id if p else None)
        return _compact({"product_id": p.id if p else None, "product": safe_label(name),
                         "margin": ctx.cite(f"{prefix}.margin", f"{name} margin"),
                         "gross_profit": ctx.cite(f"{prefix}.gross_profit", f"{name} gross profit"),
                         "revenue": ctx.cite(f"{prefix}.revenue", f"{name} revenue")})

    return _compact({
        "window_start": ctx.cite("margin.last_90d.start", "Margin window start"),
        "window_end": ctx.cite("margin.last_90d.end", "Margin window end"),
        "revenue": ctx.cite("margin.last_90d.revenue", "Revenue, last quarter"),
        "cost_of_goods": ctx.cite("margin.last_90d.cogs", "Cost of goods, last quarter"),
        "gross_profit": ctx.cite("margin.last_90d.gross_profit", "Gross profit, last quarter"),
        "gross_margin": ctx.cite("margin.last_90d.gross_margin", "Gross margin, last quarter"),
        "highest_margin_products": [product(s) for _, s in reversed(ranked[-3:])],
        "lowest_margin_products": [product(s) for _, s in ranked[:3]],
        "products_selling_at_a_loss": [product(s) for v, s in ranked if v < 0],
    })


# get_kpis -------------------------------------------------------------------------------------------------------

def get_kpis(ctx: TurnContext, _: NoArgs) -> dict[str, Any]:
    kpis = []
    for b in ctx.computed.benchmarks:
        kpis.append(_compact({
            "kpi": b.kpi_id,
            "label": safe_label(b.label),
            "status": b.status,
            "value": ctx.cite(b.value_fact_id, b.label) if b.value_fact_id else None,
            "healthy_min": ctx.cite(b.healthy_min_fact_id, f"{b.label}, healthy minimum")
            if b.healthy_min_fact_id else None,
            "healthy_max": ctx.cite(b.healthy_max_fact_id, f"{b.label}, healthy maximum")
            if b.healthy_max_fact_id else None,
        }))
    return {"kpis": kpis, "note": "Healthy ranges come from the Skill Pack and are synthetic benchmarks."}


# list_receivables / list_upcoming_bills -------------------------------------------------------------------------

class ReceivablesArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    only_overdue: bool = False


class BillsArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    within_days: int = Field(30, ge=1, le=90, description="Bills due from today up to this many days ahead, "
                                                          "plus any already overdue.")


# Scheduled items from the business's own records. Anything else (e.g. due dates the extractor read from an email)
# is untrusted: its IDs are not trusted and its facts force owner approval when used in an action (invariant 3).
# owner_entered: bills the owner typed in at onboarding. Amounts read from uploaded documents keep an untrusted
# source even after the owner approves them (services/onboarding.DOCUMENT_SOURCE).
TRUSTED_SCHEDULE_SOURCES = frozenset({"contract", "invoice", "estimate", "owner_entered"})


def _scheduled_entry(ctx: TurnContext, item, id_key: str, party_key: str) -> dict[str, Any]:
    p = scheduled_prefix(item.id)
    who = ctx.profile.counterparty_names.get(item.counterparty_id or "", "unknown")
    spec = ctx.computed.inputs.pack.categories.get(item.category)
    trusted = item.source in TRUSTED_SCHEDULE_SOURCES
    if trusted:
        ctx.trust(item.id, item.counterparty_id)
    else:
        ctx.distrust([f"{p}.amount", f"{p}.due_date", f"{p}.days_overdue"], item.id, item.counterparty_id)
    return _compact({
        "provenance": "trusted" if trusted else "untrusted",
        id_key: item.id,
        party_key: item.counterparty_id,
        "name": who,
        "category": safe_label(spec.label if spec else item.category.replace("_", " ")),
        "amount": ctx.cite(f"{p}.amount", f"{who} amount"),
        "due_date": ctx.cite(f"{p}.due_date", f"{who} due date"),
        "days_overdue": ctx.cite(f"{p}.days_overdue", f"{who} days overdue"),
        "status": "overdue" if item.due_date < ctx.clock.today() else "not_yet_due",
    })


def list_receivables(ctx: TurnContext, a: ReceivablesArgs) -> dict[str, Any]:
    today = ctx.clock.today()
    items = [s for s in ctx.computed.inputs.scheduled
             if s.kind == "receivable" and s.status == "open" and (not a.only_overdue or s.due_date < today)]
    return _compact({
        "invoices": [_scheduled_entry(ctx, s, "invoice_id", "customer_id") for s in items],
        "total_overdue": ctx.cite("forecast.overdue_receivables", "Overdue customer invoices"),
        "note": "IDs are for tool arguments only. In replies, name the customer instead.",
    })


def list_upcoming_bills(ctx: TurnContext, a: BillsArgs) -> dict[str, Any]:
    until = ctx.clock.today() + timedelta(days=a.within_days)
    items = [s for s in ctx.computed.inputs.scheduled
             if s.kind == "payable" and s.status == "open" and s.due_date <= until]
    return {"bills": [_scheduled_entry(ctx, s, "bill_id", "payee_id") for s in items],
            "note": "IDs are for tool arguments only. In replies, name the payee instead."}


# list_leaks -----------------------------------------------------------------------------------------------------

# Owner-facing words for each detail fact a finding carries (leak.<detector>.<key>.<metric>).
LEAK_DETAIL_LABELS = {
    "monthly": "redundant charge per month", "months": "months double-billed",
    "first_unit_cost": "first unit cost", "latest_unit_cost": "latest unit cost", "first_date": "first purchase",
    "latest_date": "latest purchase", "increase": "unit cost increase", "purchases": "purchases compared",
    "fees": "fees paid in the window", "fee_share": "fee share of digital sales", "healthy_share": "typical range",
    "lookback": "window", "paid": "late fees paid", "charges": "late fee charges", "refunds": "refunds paid",
    "revenue": "revenue", "cost": "supplier cost", "gross_profit": "gross profit", "margin": "margin",
    "since": "since", "missed": "discounts missed", "invoices": "invoices paid after the deadline",
    "discount_rate": "discount offered", "stock_value": "stock value", "units_on_hand": "units on hand",
    "units_bought": "units bought", "sell_through": "share sold", "days_held": "time held",
    "spend": "ad spend", "attributed_sales": "sales from the ads", "roas": "return on ad spend",
    "return_rate": "return rate", "returned": "units returned", "sold": "units sold", "refunded": "refunded",
    "healthy_rate": "expected return rate",
}


def leak_subject(finding, products, names: dict[str, str]) -> str | None:
    """Digit-free name of what a finding is about, from the business's own records (never statement text)."""
    parts = []
    if (sid := finding.subject.get("supplier_id")):
        parts.append(names.get(sid, "a supplier"))
    if (pid := finding.subject.get("product_id")):
        product = next((p for p in products if p.id == pid), None)
        parts.append(safe_label(product.name if product else pid))
    if (group := finding.subject.get("group")):
        parts.append(safe_label(group.replace("_", " ")))
    if (campaign := finding.subject.get("campaign")):
        parts.append(safe_label(campaign))
    return ", ".join(parts) or None


def list_leaks(ctx: TurnContext, _: NoArgs) -> dict[str, Any]:
    inputs = ctx.computed.inputs
    labels = detector_labels(inputs.pack)
    findings = []
    for f in sorted(ctx.computed.leaks, key=lambda f: (-f.impact.value, f.id)):
        label = labels.get(f.detector, f.detector.replace("_", " "))
        about = leak_subject(f, inputs.products, ctx.profile.counterparty_names)
        ctx.trust(*f.subject.values())
        details = {}
        for d in f.details:
            metric = d.id.rsplit(".", 1)[1]
            words = LEAK_DETAIL_LABELS.get(metric, metric.replace("_", " "))
            details[safe_label(words)] = ctx.cite(d.id, f"{label}: {words}")
        findings.append(_compact({
            "finding": safe_label(label), "detector": f.detector, "about": about, **f.subject,
            "yearly_impact": ctx.cite(f.impact.id, f"{label}{': ' + about if about else ''}, per year"),
            "details": details,
        }))
    return {"findings": findings,
            "note": "Largest first. Yearly impact is estimated from the evidence rows; the owner can click any "
                    "figure to see them. IDs are for tool arguments only; in replies, use the names."}


# explain_fact ---------------------------------------------------------------------------------------------------

class ExplainArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    fact_id: str = Field(max_length=128, description="A fact ID from an earlier tool result, without braces.")


def explain_fact(ctx: TurnContext, a: ExplainArgs) -> dict[str, Any]:
    fact_id = a.fact_id.removeprefix("{fact:").removesuffix("}")
    if fact_id not in ctx.store:
        raise ToolError("unknown fact: call a tool that returns it first")
    store = ctx.computed.store
    # include_text=False: row text is untrusted statement content and never reaches the planner (invariant 2).
    trace = explain(fact_id, store, resolver(ctx.computed.inputs), max_rows=200, include_text=False)
    fact = store.get(fact_id)
    # Account-level inputs embed a PII token; the planner gets the business-level facts only.
    inputs = [f.id for f in trace.facts[1:] if not TOKEN.search(f.id)][:8]
    categories = sorted({r.category for r in trace.rows if r.category})[:10]
    return _compact({
        "fact": ctx.cite(fact_id, ctx.conversation.seen_fact_ids.get(fact_id, fact_id)),
        "computed_by": safe_label(fact.computed_by, 80),
        "computed_from": [ctx.cite(i, i.replace(".", " ").replace("_", " ")) for i in inputs],
        "source_row_kinds": sorted({r.kind for r in trace.rows}),
        "source_categories": [safe_label(c) for c in categories],
        "note": "The owner can click the number to see every source row.",
    })


# list_inbox -----------------------------------------------------------------------------------------------------

class InboxArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    only_flagged: bool = Field(False, description="Only messages the Inbox Sentinel flagged.")


def list_inbox(ctx: TurnContext, a: InboxArgs) -> dict[str, Any]:
    """Typed inbox fields only (invariant 2): enums, IDs, flags and fact placeholders; never subject, body or names
    from the message. Everything here came from untrusted content, so its facts and IDs are marked untrusted
    (invariant 3) and any action built on them needs the owner's signature."""
    items = []
    for r in reversed(ctx.inbox):
        rep = r.sentinel
        if a.only_flagged and not rep.flags:
            continue
        p = inbox_prefix(r.email_id)
        fact_ids = [f"{p}.amount", f"{p}.due_date", f"{p}.received"]
        ctx.distrust(fact_ids, r.email_id,
                     *(() if rep.risk == "none" else (rep.claimed_counterparty_id, rep.payee_counterparty_id)))
        party = rep.sender_counterparty_id or rep.claimed_counterparty_id
        who = ctx.profile.counterparty_names.get(party or "", "unknown sender")
        items.append(_compact({
            "inbox_id": r.email_id,
            "provenance": "untrusted",
            "category": r.fields.category,
            "sender": rep.sender_status,
            "counterparty_id": rep.sender_counterparty_id,
            "claims_to_be": rep.claimed_counterparty_id if rep.sender_status != "known" else None,
            "name": who,
            "risk": rep.risk,
            "hold": rep.hold,
            "flags": [f.code for f in rep.flags],
            "recommended": rep.recommended,
            "verification_call_required": rep.call_script is not None,
            "amount": ctx.cite(f"{p}.amount", f"{who} amount in message"),
            "due_date": ctx.cite(f"{p}.due_date", f"{who} due date in message"),
            "received": ctx.cite(f"{p}.received", f"{who} message date"),
            "forecast": r.feed,
        }))
    return {"items": items, "any_held": any(i.get("hold") for i in items),
            "note": "Values come from emails and are untrusted. Never pay a held item; the owner must verify it "
                    "by phone first. IDs are for tool arguments only."}


# registry -------------------------------------------------------------------------------------------------------

READ_TOOLS: tuple[Tool, ...] = (
    Tool("get_cash_position", "Cash balance across all accounts, cash buffer in days and how it compares with a "
         "healthy range.", NoArgs, get_cash_position),
    Tool("get_forecast", "Cash forecast: expected, bad-case and good-case balances, the lowest point and whether "
         "a shortfall is expected.", ForecastArgs, get_forecast),
    Tool("get_runway", "How long cash lasts at the current pace, and if sales drop.", NoArgs, get_runway),
    Tool("get_profit_and_loss", "Cash-basis profit and loss for a month or week, with revenue and expense lines "
         "and the change from the period before.", PnlArgs, get_profit_and_loss),
    Tool("get_margins", "Gross margin over the last quarter and the highest and lowest margin products.",
         NoArgs, get_margins),
    Tool("get_kpis", "The Skill Pack's key indicators against their healthy ranges (below, within, above).",
         NoArgs, get_kpis),
    Tool("list_receivables", "Open customer invoices: who owes what, when it was due, how overdue.",
         ReceivablesArgs, list_receivables),
    Tool("list_upcoming_bills", "Known bills due soon (rent, wages, subscriptions, suppliers), including overdue "
         "ones.", BillsArgs, list_upcoming_bills),
    Tool("list_leaks", "Money being wasted: duplicate subscriptions, payment fees, late fees, supplier price "
         "rises, products sold below cost, missed early-payment discounts, slow stock. Each with a yearly impact "
         "and supporting figures.", NoArgs, list_leaks),
    Tool("explain_fact", "How a number was computed: the facts it came from and the kinds of source rows.",
         ExplainArgs, explain_fact),
    Tool("list_inbox", "Processed inbox messages as typed fields: category, sender status, Inbox Sentinel flags "
         "and risk, amount and due date. Never message text; everything here is untrusted.",
         InboxArgs, list_inbox),
    Tool("match_financing", "Which synthetic financing products the business qualifies for, pass or fail with a "
         "reason per rule, and the repayment-safe amount under a sales-drop stress test.",
         NoFinancingArgs, match_financing),
    Tool("get_passport", "The Readiness Passport: band, the five factors behind it and the path to eligibility.",
         NoFinancingArgs, get_passport),
    Tool("get_loan_application_draft", "Prepare (not send) a draft application for an eligible product at its "
         "repayment-safe amount. Returns a draft_id for propose_action submit_loan_application.",
         DraftArgs, get_loan_application_draft),
    Tool("rank_products_for_ads", "Which products are worth advertising more and which are excluded and why (low "
         "stock, ads not covering margin, high returns), from the ad spend export and product records. Also "
         "lists known ad campaigns.", NoAdsArgs, rank_products_for_ads),
    Tool("product_performance", "One product's ad spend, return on ad spend, profit after ad spend, return rate, "
         "sales trend, margin and stock cover.", ProductArgs, product_performance),
    Tool("ad_budget_what_if", "Estimated change in gross profit, as a low/high range, from moving a budget "
         "amount from one ad campaign to another.", WhatIfArgs, ad_budget_what_if),
)


def run_tool(tool: Tool, ctx: TurnContext, raw_arguments: str) -> dict[str, Any]:
    """Validate arguments and run a tool. A bad call comes back as `{"error": ...}` for the planner to fix."""
    try:
        parsed = json.loads(raw_arguments or "{}")
        args = tool.params.model_validate(parsed if isinstance(parsed, dict) else {})
        return tool.fn(ctx, args)
    except json.JSONDecodeError:
        return {"error": "arguments are not valid JSON"}
    except ValidationError as exc:
        return {"error": "invalid arguments: " + "; ".join(
            f"{'.'.join(map(str, e['loc'])) or 'arguments'}: {e['msg']}" for e in exc.errors())}
    except ToolError as exc:
        return {"error": str(exc)}
