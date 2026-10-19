"""Onboarding from zero. Thin routes over services/onboarding.py; every step is audited there."""

from typing import Annotated, Literal

from fastapi import APIRouter, File, UploadFile
from pydantic import BaseModel, Field

from app.api.deps import BusinessId, RuntimeDep
from app.quarantine.store import InboxRecord
from app.services import onboarding as ob
from app.services.businesses import BusinessInfo

router = APIRouter(tags=["onboarding"])


class NewBusiness(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    business_type: str = Field(min_length=1, max_length=80, description="The owner's own words; picks the Skill Pack")
    currency: str = Field(default="USD", min_length=3, max_length=3)


class StartingPoint(BaseModel):
    cash_on_hand_minor: int | None = Field(default=None, ge=0, le=10**13)
    bills: list[ob.Bill] = Field(default_factory=list, max_length=12)


class Answer(BaseModel):
    question_id: str
    option: int = Field(ge=0, le=10)


class Skip(BaseModel):
    need_id: str


class Contacts(BaseModel):
    contacts: list[ob.ContactIn] = Field(max_length=40)


class InboxChoice(BaseModel):
    connection: Literal["sandbox", "gmail"]


class ResetResult(BaseModel):
    deleted: list[str]


@router.post("/onboarding", response_model=BusinessInfo)
def start_onboarding(body: NewBusiness, rt: RuntimeDep) -> BusinessInfo:
    """Create a new business with its own ledger. Its type picks the Skill Pack (general pack if nothing matches)."""
    return ob.create_business(rt, body.name, body.business_type, body.currency.upper())


@router.post("/onboarding/reset", response_model=ResetResult)
def reset_onboarding(rt: RuntimeDep) -> ResetResult:
    """Delete every business created by onboarding (rehearsals). Seeded businesses are never touched."""
    return ResetResult(deleted=ob.reset(rt))


@router.get("/businesses/{business_id}/onboarding", response_model=ob.OnboardingView)
def get_onboarding(business_id: BusinessId, rt: RuntimeDep) -> ob.OnboardingView:
    """Where onboarding stands: the pack's plan, answers, uploads, contact proposals, summary and starter limits."""
    return ob.view(rt, business_id)


@router.put("/businesses/{business_id}/onboarding/starting-point", response_model=ob.OnboardingView)
def put_starting_point(business_id: BusinessId, body: StartingPoint, rt: RuntimeDep) -> ob.OnboardingView:
    ob.set_starting_point(rt, business_id, body.cash_on_hand_minor, body.bills)
    return ob.view(rt, business_id)


@router.post("/businesses/{business_id}/onboarding/answers", response_model=ob.OnboardingView)
def post_answer(business_id: BusinessId, body: Answer, rt: RuntimeDep) -> ob.OnboardingView:
    ob.answer(rt, business_id, body.question_id, body.option)
    return ob.view(rt, business_id)


@router.post("/businesses/{business_id}/onboarding/skip", response_model=ob.OnboardingView)
def post_skip(business_id: BusinessId, body: Skip, rt: RuntimeDep) -> ob.OnboardingView:
    ob.skip_need(rt, business_id, body.need_id)
    return ob.view(rt, business_id)


@router.post("/businesses/{business_id}/onboarding/uploads", response_model=ob.UploadResult)
async def post_upload(business_id: BusinessId, rt: RuntimeDep,
                      file: Annotated[UploadFile, File(description="CSV, PDF invoice or receipt image")]
                      ) -> ob.UploadResult:
    """One file. CSVs are recognised by their columns; PDFs and images go to the quarantined extractor."""
    data = await file.read(ob.MAX_UPLOAD_BYTES + 1)
    return ob.upload(rt, business_id, file.filename or "upload", data)


@router.get("/businesses/{business_id}/onboarding/documents/{email_id}", response_model=InboxRecord)
def get_document(business_id: BusinessId, email_id: str, rt: RuntimeDep) -> InboxRecord:
    """What the extractor read from an uploaded document and what the sentinel found (owner view)."""
    return ob.document_view(rt, business_id, email_id)


@router.post("/businesses/{business_id}/onboarding/documents/{email_id}/approve")
def approve_document(business_id: BusinessId, email_id: str, rt: RuntimeDep) -> dict[str, str]:
    """Use a document's amount. Refused for flagged documents; the amount keeps an untrusted source."""
    return ob.approve_document(rt, business_id, email_id)


@router.post("/businesses/{business_id}/onboarding/contacts", response_model=ob.OnboardingView)
def post_contacts(business_id: BusinessId, body: Contacts, rt: RuntimeDep) -> ob.OnboardingView:
    ob.confirm_contacts(rt, business_id, body.contacts)
    return ob.view(rt, business_id)


@router.put("/businesses/{business_id}/onboarding/inbox", response_model=ob.OnboardingView)
def put_inbox(business_id: BusinessId, body: InboxChoice, rt: RuntimeDep) -> ob.OnboardingView:
    ob.set_inbox(rt, business_id, body.connection)
    return ob.view(rt, business_id)


@router.post("/businesses/{business_id}/onboarding/finish", response_model=ob.FinishResult)
def post_finish(business_id: BusinessId, rt: RuntimeDep) -> ob.FinishResult:
    """Mark onboarding done and write the first Morning Brief now."""
    return ob.finish(rt, business_id)


@router.delete("/businesses/{business_id}", response_model=ResetResult)
def delete_business(business_id: BusinessId, rt: RuntimeDep) -> ResetResult:
    """Delete a business created by onboarding. Seeded businesses are refused."""
    ob.delete_business(rt, business_id)
    return ResetResult(deleted=[business_id])
