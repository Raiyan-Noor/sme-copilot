"""The planner's financing tools (Tier 1): match_financing, get_passport, get_loan_application_draft.

Registered in agent/tools.py READ_TOOLS. Same rules as every read tool (invariant 4): numbers only as
`{fact:<id>}` placeholders through `ctx.cite`, comparisons as enums, names digit-free. Product IDs and draft IDs
come from code, so they are recorded as trusted values (invariant 3) and can be used in propose_action.

get_loan_application_draft only prepares and stores a draft at the repayment-safe amount; it cannot send anything.
Sending is `submit_loan_application`, a T3 action the gateway holds until the owner signs (invariants 1 and 6).
"""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.agent.context import TurnContext, safe_label
from app.engine.application import DraftError
from app.services.financing import PassportExports, prepare_loan_draft

NOTE = ("Synthetic catalog and data. Show the owner why each product fits or not, rule by rule, and the "
        "repayment-safe size. The lender makes the credit decision; this is not regulated financial advice.")


class NoFinancingArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DraftArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    product_id: str | None = Field(None, max_length=48, description="A product_id from match_financing. Omit for "
                                                                    "the best-fitting eligible product.")


def _financing(ctx: TurnContext):
    result = ctx.computed.financing
    if result is None:
        return None
    return result


def match_financing(ctx: TurnContext, _: NoFinancingArgs) -> dict[str, Any]:
    result = _financing(ctx)
    if result is None:
        return {"error": "no financing data for this business"}
    m = result.match
    products = []
    for p in m.products:
        ctx.trust(p.product_id)
        rules = []
        for r in p.rules:
            entry = {"rule": r.rule, "label": safe_label(r.label), "passed": r.passed,
                     "business_value": ctx.cite(r.metric_fact_id, r.label),
                     "required": ctx.cite(r.threshold_fact_id, f"{r.label}, required"),
                     "comparison": "at_least" if r.op == ">=" else "at_most"}
            if r.eligible_from_fact_id:
                entry["met_from_if_trading_continues"] = ctx.cite(r.eligible_from_fact_id,
                                                                  f"{r.label}, met from")
            rules.append({k: v for k, v in entry.items() if v is not None})
        products.append({
            "product_id": p.product_id, "name": safe_label(p.name), "lender": safe_label(p.lender),
            "type": p.type, "status": p.status, "fit_for_this_business": p.fit,
            "capped_by": p.capped_by or "not_applicable",
            "repayment_safe_amount": ctx.cite(p.safe_amount_fact_id, f"{p.name} safe amount"),
            "monthly_installment": ctx.cite(p.installment_fact_id, f"{p.name} installment"),
            "term": ctx.cite(p.term_fact_id, f"{p.name} term"),
            "monthly_rate": ctx.cite(p.monthly_rate_fact_id, f"{p.name} monthly rate"),
            "rules": rules,
        })
    return {
        "max_safe_monthly_repayment": ctx.cite(m.max_installment_fact_id, "Most you can safely repay a month"),
        "stressed_monthly_surplus": ctx.cite("financing.capacity.stressed_monthly_surplus",
                                             "Monthly surplus if sales drop"),
        "sales_drop_tested": ctx.cite("financing.capacity.revenue_drop", "Sales drop tested"),
        "products": products,
        "note": NOTE + " To apply: get_loan_application_draft, then propose_action submit_loan_application.",
    }


def get_passport(ctx: TurnContext, _: NoFinancingArgs) -> dict[str, Any]:
    result = _financing(ctx)
    if result is None:
        return {"error": "no financing data for this business"}
    p = result.passport
    factors = [{"factor": f.factor, "label": f.label, "status": f.status,
                "value": ctx.cite(f.raw_fact_id, f.label)} for f in p.factors]
    steps: list[dict[str, Any]] = []
    for s in p.path_to_eligibility:
        if s.kind == "readiness":
            raw = next(f.raw_fact_id for f in p.factors if f.factor == s.factor)
            steps.append({"kind": "readiness", "factor": s.factor, "from": ctx.cite(raw, s.factor),
                          "to": ctx.cite(f"passport.path.{s.factor}.target", f"{s.factor} target"),
                          "reaches_band": safe_label(p.next_band_label)})
            continue
        ctx.trust(s.product_id)
        product = next(m for m in result.match.products if m.product_id == s.product_id)
        if product.status == "not_safe":
            steps.append({"kind": "product", "product_id": s.product_id, "name": safe_label(product.name),
                          "blocker": "repayment_capacity_below_product_minimum",
                          "max_safe_monthly_repayment": ctx.cite(result.match.max_installment_fact_id,
                                                                 "Most you can safely repay a month"),
                          "product_minimum": ctx.cite(product.min_amount_fact_id, f"{product.name} minimum")})
            continue
        for r in product.rules:
            if r.passed or r.reason not in s.text:
                continue
            step = {"kind": "product", "product_id": s.product_id, "name": safe_label(product.name),
                    "rule": r.rule, "business_value": ctx.cite(r.metric_fact_id, r.label),
                    "required": ctx.cite(r.threshold_fact_id, f"{r.label}, required")}
            if r.eligible_from_fact_id:
                step["met_from_if_trading_continues"] = ctx.cite(r.eligible_from_fact_id, f"{r.label}, met from")
            steps.append(step)
    return {
        "band": p.band_id,
        "band_label": safe_label(p.band_label),
        "next_band": safe_label(p.next_band_label) if p.next_band_label else "already_top_band",
        "score": ctx.cite(p.score_fact_id, "Readiness score"),
        "factors": factors,
        "path_to_eligibility": steps,
        "eligible_product_ids": list(p.eligible_product_ids),
        "note": "The owner can export the Passport as a signed-off file whose hash is recorded for anchoring. "
                + NOTE,
    }


def get_loan_application_draft(ctx: TurnContext, a: DraftArgs) -> dict[str, Any]:
    result = _financing(ctx)
    if result is None:
        return {"error": "no financing data for this business"}
    eligible = [m for m in result.match.products if m.status == "eligible"]  # best fit first
    product_id = a.product_id or (eligible[0].product_id if eligible else None)
    if product_id is None:
        return {"error": "no product is eligible yet; use get_passport for the path to eligibility"}
    if ctx.gateway.data_dir is None:
        return {"error": "drafts need a business folder"}
    try:
        draft = prepare_loan_draft(
            business_id=ctx.business_id, result=result, store=ctx.computed.store,
            exports=PassportExports(ctx.gateway.data_dir / "passports"), drafts=ctx.gateway.loan_drafts,
            audit=ctx.audit, product_id=product_id)
    except DraftError as exc:
        return {"error": f"cannot prepare this application: {exc.rule}"}
    m = next(p for p in result.match.products if p.product_id == product_id)
    ctx.trust(product_id, draft.draft_id)
    return {
        "draft_id": draft.draft_id,
        "product_id": product_id,
        "name": safe_label(m.name),
        "amount": ctx.cite(m.safe_amount_fact_id, f"{m.name} safe amount"),
        "monthly_installment": ctx.cite(m.installment_fact_id, f"{m.name} installment"),
        "term": ctx.cite(m.term_fact_id, f"{m.name} term"),
        "status": "draft_saved_not_sent",
        "next_step": ("To send it, call propose_action with tool submit_loan_application and args product_id, "
                      "draft_id exactly as given here, and amount_minor as the fact of the amount above. "
                      "The owner must sign before anything is sent."),
    }
