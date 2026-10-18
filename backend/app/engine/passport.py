"""The Readiness Passport: band, reasons and path to eligibility, and its canonical JSON export.

Built from Facts only (invariant 4): the raw factors (engine.readiness_factors), the pack-weighted score and band
(packs.readiness), and the financing match. Every reason and path step is code-written text with `{fact:<id>}`
placeholders and no digits outside them, rendered with the Numeric Firewall renderer, so each number links to its
trace.

Path to eligibility has two kinds of steps:
- `readiness`: for each factor, the raw value that alone would lift the score to the next band (other factors
  unchanged). Only factors that can get there on their own are listed, smallest change in factor score first.
- `product`: for the closest products the business does not qualify for yet, the rules it fails and, for history
  rules, the date it will meet them if it keeps trading; or, when every rule passes but the safe size is below the
  product minimum, that the repayment capacity is the blocker.

Export (`passport_document`) is canonical JSON (audit.canonical): sorted keys, no floats (ratios become decimal
strings), so anyone can recompute its SHA-256 from the file and check it against the anchored hash (invariant 9).
It carries no raw statement text; numbers come with their fact IDs and how they were computed.
"""

from collections.abc import Mapping
from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from app.engine.common import days, ratio
from app.engine.financing import FinancingMatch
from app.firewall.fact import Fact
from app.firewall.render import render
from app.firewall.store import FactStore
from app.packs.readiness import ReadinessResult
from app.packs.schema import READINESS_FACTORS, Pack

BY = "engine.passport"
SCHEMA = "readiness_passport/v1"
MAX_PRODUCT_STEPS = 4
MAX_FAILED_RULES = 2

FactorStatus = Literal["strong", "fair", "weak"]

LABELS = {
    "inflow_regularity": "Sales regularity",
    "revenue_stability": "Sales stability",
    "buffer_days": "Cash buffer",
    "collection_days": "Days to collect from customers",
    "payment_punctuality": "Supplier bills paid on time",
}
EXPLAINS = {
    "inflow_regularity": "share of recent days with sales coming in",
    "revenue_stability": "how steady weekly sales are",
    "buffer_days": "days of spending today's cash covers",
    "collection_days": "average days until customers pay an invoice",
    "payment_punctuality": "share of supplier invoices paid by their due date",
}


class PassportFactor(BaseModel):
    model_config = ConfigDict(frozen=True)

    factor: str
    label: str
    explains: str
    weight_fact_id: str
    raw_fact_id: str
    score_fact_id: str
    status: FactorStatus
    reason: str


class PathStep(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: Literal["readiness", "product"]
    factor: str | None = None
    product_id: str | None = None
    text: str


class Passport(BaseModel):
    model_config = ConfigDict(frozen=True)

    schema_id: Literal["readiness_passport/v1"] = SCHEMA
    synthetic_data: bool
    as_of: date
    business_id: str
    business_name: str
    currency: str
    pack_ref: str
    catalog_ref: str
    band_id: str
    band_label: str
    next_band_label: str | None
    score_fact_id: str
    factors: list[PassportFactor]
    reasons: list[str]
    path_to_eligibility: list[PathStep]
    eligible_product_ids: list[str]


def _status(score: float) -> FactorStatus:
    return "strong" if score >= 0.75 else "fair" if score >= 0.4 else "weak"


def _raw_like(fid: str, factor: str, value: float, inputs: list[str]) -> Fact:
    if factor in ("buffer_days", "collection_days"):
        return days(fid, value, BY, inputs=inputs)
    return ratio(fid, value, BY, inputs=inputs)


def build_passport(*, raw: Mapping[str, Fact], readiness: ReadinessResult, match: FinancingMatch, pack: Pack,
                   as_of: date, business_id: str, business_name: str, currency: str, synthetic_data: bool) -> tuple[Passport, list[Fact]]:
    """The Passport and the Facts it adds (factor weights, next-band threshold, path targets)."""
    out: list[Fact] = []
    pack_src = f"{pack.ref}#readiness"
    factors: list[PassportFactor] = []
    for name in READINESS_FACTORS:
        spec = pack.readiness.factors[name]
        weight = ratio(f"passport.weight.{name}", spec.weight, BY, [f"{pack_src}.factors.{name}"])
        out.append(weight)
        score = readiness.factor_scores[name]
        status = _status(float(score.value))
        factors.append(PassportFactor(
            factor=name, label=LABELS[name], explains=EXPLAINS[name], weight_fact_id=weight.id,
            raw_fact_id=raw[name].id, score_fact_id=score.id, status=status,
            reason=f"{LABELS[name]} is {status} at {{fact:{raw[name].id}}}"))

    by_weight = sorted(factors, key=lambda f: -pack.readiness.factors[f.factor].weight)
    reasons = [f"Strength: {f.reason}" for f in by_weight if f.status == "strong"]
    reasons += [f"Holding back: {f.reason}" for f in by_weight if f.status == "weak"]
    if not reasons:
        reasons = [f"Every factor is fair; the score is {{fact:{readiness.score.id}}}"]

    path: list[PathStep] = []
    bands = list(pack.readiness.bands)
    idx = next(i for i, b in enumerate(bands) if b.id == readiness.band_id)
    next_band = bands[idx - 1] if idx > 0 else None
    if next_band is not None:
        target_id = "passport.next_band.min_score"
        out.append(ratio(target_id, next_band.min_score, BY, [f"{pack_src}.bands.{next_band.id}"]))
        gap = next_band.min_score - float(readiness.score.value)
        options = []
        for f in factors:
            spec = pack.readiness.factors[f.factor]
            current = float(readiness.factor_scores[f.factor].value)
            needed = current + gap / spec.weight
            if needed <= 1.0:
                options.append((needed - current, f, spec.worst + needed * (spec.best - spec.worst)))
        for _, f, target in sorted(options, key=lambda o: o[0]):
            fid = f"passport.path.{f.factor}.target"
            out.append(_raw_like(fid, f.factor, target, [f.raw_fact_id, readiness.score.id, target_id]))
            verb = "Cut" if f.factor == "collection_days" else "Raise"
            path.append(PathStep(kind="readiness", factor=f.factor, text=(
                f"{verb} {f.label.lower()} from {{fact:{f.raw_fact_id}}} to {{fact:{fid}}} to reach the "
                f"{next_band.label} band")))

    product_steps = 0
    for m in match.products:
        if product_steps >= MAX_PRODUCT_STEPS or m.status == "eligible":
            continue
        failed = [r for r in m.rules if not r.passed]
        if m.status == "not_safe":
            path.append(PathStep(kind="product", product_id=m.product_id, text=(
                f"{m.name}: every rule is met, but the most you can safely repay each month, "
                f"{{fact:{match.max_installment_fact_id}}}, does not cover its smallest loan of "
                f"{{fact:{m.min_amount_fact_id}}}")))
            product_steps += 1
        elif len(failed) <= MAX_FAILED_RULES and m.fit != "weak":
            for r in failed:
                path.append(PathStep(kind="product", product_id=m.product_id, text=f"{m.name}: {r.reason}"))
            product_steps += 1

    return Passport(
        synthetic_data=synthetic_data, as_of=as_of, business_id=business_id, business_name=business_name,
        currency=currency, pack_ref=pack.ref, catalog_ref=match.catalog_ref, band_id=readiness.band_id,
        band_label=readiness.band_label, next_band_label=next_band.label if next_band else None,
        score_fact_id=readiness.score.id, factors=factors, reasons=reasons, path_to_eligibility=path,
        eligible_product_ids=[m.product_id for m in match.products if m.status == "eligible"],
    ), out


# Export ---------------------------------------------------------------------------------------------------------

def _value(v: Any) -> Any:
    if isinstance(v, float):
        return format(v, ".6g")  # canonical JSON has no floats
    if isinstance(v, date):
        return v.isoformat()
    return v


def _fact_entry(f: Fact) -> dict[str, Any]:
    return {"value": _value(f.value), "unit": f.unit, "display": f.display, "currency": f.currency,
            "computed_by": f.computed_by, "inputs": list(f.inputs), "source_rows": len(f.source_row_ids)}


def _closure(ids: list[str], store: FactStore) -> list[str]:
    seen: list[str] = []
    stack = list(ids)
    while stack:
        fid = stack.pop()
        if fid in seen or fid not in store:
            continue
        seen.append(fid)
        stack.extend(store.get(fid).inputs)
    return sorted(seen)


def passport_document(passport: Passport, match: FinancingMatch, store: FactStore) -> dict[str, Any]:
    """The exportable Passport: rendered text, the facts behind every number and the per-product rule results.

    Deterministic for a given ledger, pack, catalog and simulated date; contains no floats and no statement text.
    """
    def text(template: str) -> str:
        return render(template, store).text

    cited: list[str] = [passport.score_fact_id, match.max_installment_fact_id]
    factors = []
    for f in passport.factors:
        cited += [f.raw_fact_id, f.score_fact_id, f.weight_fact_id]
        factors.append({"factor": f.factor, "label": f.label, "explains": f.explains, "status": f.status,
                        "raw": f.raw_fact_id, "score": f.score_fact_id, "weight": f.weight_fact_id,
                        "reason": text(f.reason)})
    products = []
    for m in match.products:
        cited += [m.safe_amount_fact_id, m.installment_fact_id, m.term_fact_id, m.monthly_rate_fact_id]
        rules = []
        for r in m.rules:
            cited += [r.metric_fact_id, r.threshold_fact_id] + ([r.eligible_from_fact_id] if r.eligible_from_fact_id
                                                                 else [])
            rules.append({"rule": r.rule, "passed": r.passed, "reason": text(r.reason)})
        products.append({"product_id": m.product_id, "name": m.name, "lender": m.lender, "type": m.type,
                         "status": m.status, "capped_by": m.capped_by, "safe_amount": m.safe_amount_fact_id,
                         "installment": m.installment_fact_id, "term": m.term_fact_id,
                         "monthly_rate": m.monthly_rate_fact_id, "rules": rules})
    steps = []
    for s in passport.path_to_eligibility:
        steps.append({"kind": s.kind, "factor": s.factor, "product_id": s.product_id, "text": text(s.text)})
    for template in (*passport.reasons, *(s.text for s in passport.path_to_eligibility)):
        cited += [fid for fid in render(template, store).fact_ids]
    return {
        "schema": passport.schema_id,
        "synthetic_data": passport.synthetic_data,
        "as_of": passport.as_of.isoformat(),
        "business": {"id": passport.business_id, "name": passport.business_name},
        "currency": passport.currency,
        "pack": passport.pack_ref,
        "catalog": passport.catalog_ref,
        "band": {"id": passport.band_id, "label": passport.band_label, "next": passport.next_band_label},
        "score": passport.score_fact_id,
        "factors": factors,
        "reasons": [text(r) for r in passport.reasons],
        "path_to_eligibility": steps,
        "financing": {"max_installment": match.max_installment_fact_id, "products": products},
        "facts": {fid: _fact_entry(store.get(fid)) for fid in _closure(cited, store)},
        "disclaimer": ("Synthetic demo data. Readiness is an indicator, not a credit decision; lenders decide. "
                       "Not regulated financial advice."),
    }
