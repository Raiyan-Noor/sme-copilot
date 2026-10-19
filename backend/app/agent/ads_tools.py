"""The planner's ad advisor tools (Tier 1): rank_products_for_ads, product_performance, ad_budget_what_if.

Registered in agent/tools.py READ_TOOLS. Same rules as every read tool (invariant 4): numbers only as
`{fact:<id>}` placeholders through `ctx.cite`, reasons and trends as enums computed in code, names digit-free
(invariant 2). Product and campaign IDs come from the business's own uploaded products and ad-spend files, so
they are trusted values (invariant 3) usable as tool arguments, the same way `get_margins` trusts product IDs.

`ad_budget_what_if` is the one tool here that computes fresh Facts from an owner-chosen amount instead of only
citing ones already computed for the business at request time (services/finance.py `compute`). engine/ad_advisor.py
does the arithmetic and returns Facts that trace to the campaigns' ad spend rows; `_cite_added` registers them in
this turn's FactStore the same way `ctx.cite` would, so the Numeric Firewall still only renders a number this
request actually computed, never a remembered or invented one.
"""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.agent.context import TurnContext, safe_label
from app.engine.ad_advisor import ad_budget_what_if as _what_if
from app.engine.common import slug

EXCLUSION_LABELS = {
    "low_stock_cover": "Low stock on hand: restock before advertising this more.",
    "negative_profit_after_ads": "Margin does not cover what ads on this product cost, even though sales look ok.",
    "high_return_rate": "Returns are eating into what the ads bring in.",
}

NOTE = ("Ranked by profit after ad spend (margin on attributed sales minus what was spent reaching them), "
       "excluding products flagged below. Only products whose ad spend export names them are covered.")


class NoAdsArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _cite_added(ctx: TurnContext, fact_id: str, label: str) -> str:
    """Like `ctx.cite`, for a Fact this turn computed fresh and already added to `ctx.store` (not in the
    business's precomputed pool, because it depends on an owner-chosen amount)."""
    label = safe_label(label)
    ctx.cited.setdefault(fact_id, label)
    ctx.conversation.seen_fact_ids.setdefault(fact_id, label)
    return "{fact:" + fact_id + "}"


def _campaigns(ctx: TurnContext) -> list[dict[str, Any]]:
    out = []
    for c in ctx.computed.ads.campaigns:
        ctx.trust(c.id)
        pre = f"ads.campaign.{slug(c.id)}"
        out.append({
            "campaign_id": c.id, "campaign": safe_label(c.name), "channel": safe_label(c.channel),
            "spend": ctx.cite(f"{pre}.spend", f"{c.name} spend"),
            "attributed_sales": ctx.cite(f"{pre}.attributed_sales", f"{c.name} attributed sales"),
            "return_on_ad_spend": ctx.cite(f"{pre}.roas", f"{c.name} return on ad spend"),
        })
    return out


def _product_entry(ctx: TurnContext, product_id: str) -> dict[str, Any]:
    perf = ctx.computed.ad_advisor.by_product.get(product_id)
    product = next((p for p in ctx.computed.inputs.products if p.id == product_id), None)
    name = product.name if product else product_id
    ctx.trust(product_id)
    entry: dict[str, Any] = {"product_id": product_id, "product": safe_label(name)}
    if perf is None:
        entry["has_ad_data"] = False
        entry["note"] = "No ad spend export names this product."
        return entry
    entry.update({
        "has_ad_data": True,
        "ad_spend": ctx.cite(perf.spend_fact, f"{name} ad spend") if perf.spend_fact else None,
        "attributed_sales": ctx.cite(perf.attributed_sales_fact, f"{name} attributed sales")
        if perf.attributed_sales_fact else None,
        "return_on_ad_spend": ctx.cite(perf.roas_fact, f"{name} return on ad spend") if perf.roas_fact else None,
        "profit_after_ad_spend": ctx.cite(perf.profit_after_ads_fact, f"{name} profit after ad spend")
        if perf.profit_after_ads_fact else None,
        "return_rate": ctx.cite(perf.return_rate_fact, f"{name} return rate") if perf.return_rate_fact else None,
        "units_sold_trend": perf.units_trend,
        "worth_promoting_more": product_id in ctx.computed.ad_advisor.ranked,
        "exclusion_reasons": [{"reason": r, "explanation": EXCLUSION_LABELS[r]} for r in perf.excluded],
    })
    return {k: v for k, v in entry.items() if v is not None}


def rank_products_for_ads(ctx: TurnContext, _: NoAdsArgs) -> dict[str, Any]:
    insights = ctx.computed.ad_advisor
    ranked = [_product_entry(ctx, pid) for pid in insights.ranked]
    excluded = [_product_entry(ctx, pid) for pid, perf in insights.by_product.items() if perf.excluded]
    return {
        "worth_promoting_more": ranked,
        "excluded": excluded,
        "campaigns": _campaigns(ctx),
        "note": NOTE if insights.by_product else
        "No ad spend export links a campaign to a product for this business yet.",
    }


class ProductArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    product_id: str | None = Field(None, max_length=48, description="A product_id from rank_products_for_ads or "
                                                                     "get_margins. Omit for the top-ranked product.")


def product_performance(ctx: TurnContext, a: ProductArgs) -> dict[str, Any]:
    insights = ctx.computed.ad_advisor
    product_id = a.product_id or (insights.ranked[0] if insights.ranked else ctx.computed.products.best_margin)
    if product_id is None or not any(p.id == product_id for p in ctx.computed.inputs.products):
        return {"error": f"unknown product_id {product_id!r}" if product_id else "no product data for this business"}
    entry = _product_entry(ctx, product_id)
    pre = f"margin.product.{slug(product_id)}.last_90d"
    entry["gross_margin_last_quarter"] = ctx.cite(f"{pre}.margin", "gross margin, last quarter")
    entry["days_of_stock_cover"] = ctx.cite(f"product.{slug(product_id)}.days_of_cover", "days of stock cover")
    return {k: v for k, v in entry.items() if v is not None}


class WhatIfArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    from_campaign_id: str | None = Field(None, max_length=48, description="campaign_id to move budget away from, "
                                                                          "from rank_products_for_ads.")
    to_campaign_id: str | None = Field(None, max_length=48, description="campaign_id to move budget to.")
    amount_minor: int = Field(100_000, gt=0, le=10_000_000_00, description="Budget to move, in minor currency "
                                                                           "units.")


def _campaign_margin(ctx: TurnContext, campaign_id: str) -> float | None:
    """The margin of the one product this campaign promotes, if its ad spend rows name a single product;
    otherwise the business's overall gross margin, so the estimate still has a margin to apply."""
    products = {a.product_id for a in ctx.computed.inputs.ad_spend if a.campaign_id == campaign_id and a.product_id}
    if len(products) == 1:
        margin = ctx.value(f"margin.product.{slug(next(iter(products)))}.last_90d.margin")
        if isinstance(margin, float):
            return margin
    overall = ctx.value("margin.last_90d.gross_margin")
    return overall if isinstance(overall, float) else None


def ad_budget_what_if(ctx: TurnContext, a: WhatIfArgs) -> dict[str, Any]:
    campaigns = sorted(ctx.computed.ads.campaigns, key=lambda c: c.id)
    known = {c.id for c in campaigns}
    from_id = a.from_campaign_id or next((c.id for c in campaigns if c.roas is not None and c.roas < 1), None)
    to_id = a.to_campaign_id or next((c.id for c in campaigns if c.roas is not None and c.id != from_id), None)
    if from_id is None or to_id is None:
        return {"error": "no two campaigns with a known return to compare for this business"}
    if from_id not in known or to_id not in known:
        return {"error": "unknown campaign_id; call rank_products_for_ads first for valid campaign_ids"}
    margin = _campaign_margin(ctx, to_id)
    if margin is None:
        return {"error": "not enough margin data to estimate this"}
    result = _what_if(ctx.computed.inputs.ad_spend, ctx.clock, ctx.computed.inputs.snapshot.currency,
                      from_id, to_id, a.amount_minor, margin)
    if result is None:
        return {"error": "not enough ad spend history for one of these campaigns to estimate a return"}
    facts, whatif = result
    ctx.store.add_all(facts)
    return {
        "from_campaign_id": whatif.from_campaign_id, "to_campaign_id": whatif.to_campaign_id,
        "amount_requested": _cite_added(ctx, whatif.amount_requested_fact, "amount considered"),
        "amount_applied": _cite_added(ctx, whatif.amount_applied_fact, "amount used in the estimate"),
        "capped_to_historical_spend": whatif.capped,
        "return_on_ad_spend_from": _cite_added(ctx, whatif.roas_from_fact, "return on ad spend, from campaign"),
        "return_on_ad_spend_to": _cite_added(ctx, whatif.roas_to_fact, "return on ad spend, to campaign"),
        "estimated_gross_profit_change_low": _cite_added(ctx, whatif.profit_delta_low_fact,
                                                          "estimated profit change, low"),
        "estimated_gross_profit_change_high": _cite_added(ctx, whatif.profit_delta_high_fact,
                                                           "estimated profit change, high"),
        "note": "An estimate from each campaign's historical return over a recent and a longer window, capped so "
                "the destination campaign's past return is not stretched past 1.5x its usual spend.",
    }
