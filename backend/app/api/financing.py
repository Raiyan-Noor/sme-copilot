"""Financing match, Readiness Passport, Passport exports and draft loan applications.

Every number is a Fact (invariant 4): responses carry fact IDs plus a `facts` map, and reason texts use
`{fact:<id>}` placeholders the UI renders as clickable numbers. Matching and the Passport are T1 (read/compute).
Applying is T3: `POST .../financing/applications` builds a draft at a repayment-safe amount and proposes
`submit_loan_application` to the gateway, which always waits for the owner's signature over the exact payload,
including the content-derived draft ID (invariants 1 and 6). Exports and drafts are logged (invariant 7).
"""

from typing import Annotated

from fastapi import APIRouter, HTTPException, Path
from pydantic import BaseModel, Field

from app.api.deps import BusinessId, RuntimeDep
from app.engine.application import DraftError
from app.engine.financing import FinancingMatch
from app.engine.passport import Passport
from app.firewall.fact import Fact
from app.gateway import ArgValue, Decision, ProposedAction
from app.services.finance import Computed
from app.services.financing import (
    PassportExport,
    PassportExports,
    PassportExportSummary,
    prepare_loan_draft,
    referenced_fact_ids,
)

router = APIRouter(tags=["financing"])

Sha256 = Annotated[str, Path(pattern=r"^[0-9a-f]{64}$")]
DraftId = Annotated[str, Path(pattern=r"^lad_[a-p]{24}$")]


class FinancingResponse(BaseModel):
    """Every catalog product with pass/fail and a reason per rule, the repayment-safe size, and the facts cited."""

    as_of: str
    match: FinancingMatch
    facts: dict[str, Fact]


class PassportResponse(BaseModel):
    as_of: str
    passport: Passport
    facts: dict[str, Fact]


class LoanApplicationRequest(BaseModel):
    product_id: str = Field(pattern=r"^prd_[a-z][a-z_]*$", max_length=48)
    amount_minor: int | None = Field(default=None, gt=0, description="Defaults to the repayment-safe amount")


class LoanApplicationResponse(BaseModel):
    """The draft the owner is asked to sign for, and the gateway's decision (always pending_approval or denied)."""

    draft_id: str
    draft_sha256: str
    passport_sha256: str
    draft: dict
    decision: Decision


class LoanDraftView(BaseModel):
    draft_id: str
    sha256: str
    draft: dict


def _computed(rt, business_id: str) -> Computed:
    c = rt.facts(business_id)
    if c.financing is None:
        raise HTTPException(404, "no financing data for this business")
    return c


def _facts(c: Computed) -> dict[str, Fact]:
    return {fid: c.store.get(fid) for fid in referenced_fact_ids(c.financing) if fid in c.store}


def _exports(rt, business_id: str) -> PassportExports:
    return PassportExports(rt.data_dir / business_id / "passports")


@router.get("/businesses/{business_id}/financing", response_model=FinancingResponse)
def get_financing(business_id: BusinessId, rt: RuntimeDep) -> FinancingResponse:
    """Match every product in the synthetic catalog. The lender decides; this is not a credit decision."""
    c = _computed(rt, business_id)
    m = c.financing.match
    rt.audit.append("tool.match_financing", {
        "business_id": business_id, "caller": "api", "catalog": m.catalog_ref,
        "eligible": [p.product_id for p in m.products if p.status == "eligible"]})
    return FinancingResponse(as_of=rt.clock.today().isoformat(), match=m, facts=_facts(c))


@router.get("/businesses/{business_id}/passport", response_model=PassportResponse)
def get_passport(business_id: BusinessId, rt: RuntimeDep) -> PassportResponse:
    c = _computed(rt, business_id)
    rt.audit.append("tool.get_passport", {"business_id": business_id, "caller": "api",
                                          "band": c.financing.passport.band_id})
    return PassportResponse(as_of=rt.clock.today().isoformat(), passport=c.financing.passport, facts=_facts(c))


@router.post("/businesses/{business_id}/passport/export", response_model=PassportExport)
def export_passport(business_id: BusinessId, rt: RuntimeDep) -> PassportExport:
    """Export the Passport as canonical JSON. `sha256` is recorded in the audit log for anchoring."""
    c = _computed(rt, business_id)
    return _exports(rt, business_id).export(business_id, c.financing, c.store, rt.audit)


@router.get("/businesses/{business_id}/passport/exports", response_model=list[PassportExportSummary])
def list_passport_exports(business_id: BusinessId, rt: RuntimeDep) -> list[PassportExportSummary]:
    with rt.business(business_id):
        pass
    return _exports(rt, business_id).list()


@router.get("/businesses/{business_id}/passport/exports/{sha256}", response_model=PassportExport)
def get_passport_export(business_id: BusinessId, sha256: Sha256, rt: RuntimeDep) -> PassportExport:
    """A stored export. A file whose bytes no longer hash to its name is reported as not found."""
    with rt.business(business_id):
        pass
    item = _exports(rt, business_id).get(sha256)
    if item is None:
        raise HTTPException(404, "no intact export with this hash")
    return item


@router.post("/businesses/{business_id}/financing/applications", response_model=LoanApplicationResponse)
def prepare_application(business_id: BusinessId, body: LoanApplicationRequest,
                        rt: RuntimeDep) -> LoanApplicationResponse:
    """Prepare a draft application and ask the gateway to send it. The gateway waits for the owner's signature."""
    c = _computed(rt, business_id)
    gateway = rt.gateway(business_id)
    try:
        draft = prepare_loan_draft(business_id=business_id, result=c.financing, store=c.store,
                                   exports=_exports(rt, business_id), drafts=gateway.loan_drafts, audit=rt.audit,
                                   product_id=body.product_id, amount_minor=body.amount_minor)
    except DraftError as exc:
        raise HTTPException(422, f"draft refused: {exc.rule}") from None
    # The owner chose this in the UI; every value is trusted. T3 still requires their signature.
    action = ProposedAction(tool="submit_loan_application", args={
        "product_id": ArgValue(value=body.product_id, provenance="trusted"),
        "amount_minor": ArgValue(value=draft.document["amount_minor"], provenance="trusted"),
        "draft_id": ArgValue(value=draft.draft_id, provenance="trusted"),
    })
    decision = gateway.propose(action)
    return LoanApplicationResponse(draft_id=draft.draft_id, draft_sha256=draft.sha256,
                                   passport_sha256=draft.passport_sha256, draft=draft.document, decision=decision)


@router.get("/businesses/{business_id}/financing/applications/{draft_id}", response_model=LoanDraftView)
def get_application_draft(business_id: BusinessId, draft_id: DraftId, rt: RuntimeDep) -> LoanDraftView:
    """The exact draft an approval refers to, so the owner reads what they sign for."""
    status, doc, sha = rt.gateway(business_id).loan_drafts.load(draft_id)
    if status != "ok":
        raise HTTPException(404 if status == "unknown_draft" else 409, status)
    return LoanDraftView(draft_id=draft_id, sha256=sha, draft=doc)
