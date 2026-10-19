"""Email routes: the outbox (sent and simulated emails, and drafts waiting for a signature), people the owner can
email, adding a new address with the extra confirmation, and writing an email as the owner.

Invariants 1, 6 and 7. Nothing here sends: every email, including one the owner writes, becomes a draft and a pending
approval that only the owner's signature (the existing approve route) can execute. The routes call the Gateway, never
an executor; the gateway logs each step.
"""

from typing import Annotated

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.api.deps import BusinessId, RuntimeDep
from app.gateway import ArgValue, Decision, ProposedAction
from app.gateway.emails import MAX_BODY, MAX_SUBJECT, build_draft

router = APIRouter(tags=["emails"])

EMAIL_KINDS = frozenset({"email", "invoice_reminder", "supplier_message"})
Transport = Annotated[str, Field(description="gmail (really sent) or sandbox (simulated; `label` says why)")]


class EmailView(BaseModel):
    """One email as the owner reads it before signing, or after it went out. The body is final text: every number in
    it was rendered from a fact (planner and overnight drafts) or typed by the owner (`edited`, origin `owner`)."""

    draft_id: str
    sha256: str
    recipient_id: str
    recipient_name: str
    recipient_email: str | None
    added_by_owner: bool
    subject: str
    body: str
    reason: str
    origin: str
    edited: bool
    about: dict[str, str] = {}
    fact_ids: list[str] = []


class OutboxEmail(BaseModel):
    id: int
    ref: str
    kind: str
    on_date: str
    recipient_id: str
    recipient_name: str
    recipient_email: str | None
    subject: str
    body: str | None = None
    transport: Transport
    label: str | None = None
    origin: str | None = None
    draft_id: str | None = None
    gmail_message_id: str | None = None


class WaitingEmail(BaseModel):
    approval_id: str
    expires: str
    email: EmailView


class Outbox(BaseModel):
    sent: list[OutboxEmail]
    waiting: list[WaitingEmail]


class Contact(BaseModel):
    id: str
    name: str
    kind: str  # customer | supplier | added
    email: str


class RecipientCreate(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    email: str = Field(min_length=3, max_length=120)
    confirm_email: str = Field(min_length=3, max_length=120)
    confirmed: bool = False


class EmailCompose(BaseModel):
    recipient_id: str = Field(min_length=1, max_length=64)
    subject: str = Field(min_length=1, max_length=MAX_SUBJECT)
    body: str = Field(min_length=1, max_length=MAX_BODY)


def email_view(gw, args: dict) -> EmailView | None:
    found = gw.email_view(args)
    return EmailView(**found) if found else None


@router.get("/businesses/{business_id}/outbox", response_model=Outbox)
def get_outbox(business_id: BusinessId, rt: RuntimeDep) -> Outbox:
    """Every email sent or simulated (newest first) and the drafts waiting for the owner's signature."""
    gw = rt.gateway(business_id)
    sent = []
    for row in reversed(gw.outbox()):
        if row["kind"] not in EMAIL_KINDS:
            continue
        rcpt = gw.email_recipient(row["recipient_id"])
        sent.append(OutboxEmail(
            id=row["id"], ref=f"sbx_mail_{row['id']:06d}", kind=row["kind"], on_date=row["on_date"],
            recipient_id=row["recipient_id"], recipient_name=rcpt.name if rcpt else "", recipient_email=
            rcpt.email if rcpt else None, subject=row.get("subject") or "", body=row.get("body"),
            transport=row.get("transport", "sandbox"), label=row.get("label"), origin=row.get("origin"),
            draft_id=row.get("draft_id"), gmail_message_id=row.get("gmail_message_id")))
    waiting = []
    for a in gw.store.pending_approvals(rt.clock.today()):
        view = email_view(gw, a.args) if a.tool == "send_email" else None
        if view:
            waiting.append(WaitingEmail(approval_id=a.id, expires=a.payload.expiry.isoformat(), email=view))
    return Outbox(sent=sent, waiting=waiting)


@router.get("/businesses/{business_id}/emails/contacts", response_model=list[Contact])
def list_contacts(business_id: BusinessId, rt: RuntimeDep) -> list[Contact]:
    """People the owner can email: contacts with an address on file, then addresses the owner added."""
    return [Contact(id=i, name=n, kind=k, email=e) for i, n, k, e in rt.gateway(business_id).email_contacts()]


@router.post("/businesses/{business_id}/emails/recipients", response_model=Contact)
def add_recipient(business_id: BusinessId, body: RecipientCreate, rt: RuntimeDep) -> Contact:
    """Add an address that is not in the contact book. Needs the address typed twice and an explicit confirmation:
    a new address is the one way an email could be steered somewhere unexpected."""
    if body.email.strip().lower() != body.confirm_email.strip().lower():
        raise HTTPException(422, "the two addresses do not match")
    if not body.confirmed:
        raise HTTPException(422, "confirm that you know this address and want to email it")
    try:
        added = rt.gateway(business_id).add_email_recipient(body.name, body.email)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    return Contact(id=added.id, name=added.name, kind="added", email=added.email)


@router.post("/businesses/{business_id}/emails/draft", response_model=Decision)
def compose_email(business_id: BusinessId, body: EmailCompose, rt: RuntimeDep) -> Decision:
    """The owner writes an email. It is stored as a draft and proposed through the gateway like any other: the
    result is `pending_approval` (sign it on the approval sheet) or `denied` with the rule (unknown recipient,
    flagged sender). The owner's own words may contain digits; placeholders are not allowed."""
    gw = rt.gateway(business_id)
    if "{fact" in (body.subject + body.body).lower() or "\n" in body.subject:
        raise HTTPException(422, "write plain text: a one-line subject and a body without placeholders")
    draft_id, _ = gw.save_email_draft(build_draft(
        recipient_id=body.recipient_id, subject=body.subject.strip(), body=body.body.strip(),
        reason="You wrote this email.", origin="owner", facts=[]))
    return gw.propose(ProposedAction(tool="send_email", args={
        "recipient_id": ArgValue(value=body.recipient_id, provenance="trusted"),
        "draft_id": ArgValue(value=draft_id, provenance="trusted")}))
