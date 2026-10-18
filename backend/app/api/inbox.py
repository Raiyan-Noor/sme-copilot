"""Inbox: quarantined email processing and the Inbox Sentinel's findings, for the owner's Inbox screen.

The owner may see raw message text (detail view); the planner never does (invariant 2). Amounts and dates are
returned as Facts (invariant 4) built from the typed fields, with the inbox item as their source.
"""

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel

from app.api.deps import BusinessId, RuntimeDep
from app.firewall.fact import Fact
from app.quarantine.mime import MAX_EMAIL_BYTES, EmailParseError, parse_email
from app.quarantine.pdf import extract_pdf_text
from app.quarantine.store import InboxRecord
from app.services.businesses import business_info
from app.quarantine.facts import record_facts
from app.services.inbox import InboxProcessor, raw_path, store_for

router = APIRouter(tags=["inbox"])


class InboxItem(BaseModel):
    record: InboxRecord
    facts: list[Fact]


class InboxList(BaseModel):
    total: int
    held: int
    items: list[InboxItem]


class InboxSyncResult(BaseModel):
    processed: list[str]
    skipped_existing: int
    not_yet_delivered: int
    failed: list[str]
    held: list[str]


class InboxDetail(BaseModel):
    item: InboxItem
    body_text: str  # raw, untrusted: for the owner's eyes only
    hidden_text: list[str]  # text a human could not see in the original (hidden PDF/HTML runs)


def _currency(rt, business_id: str) -> str:
    with rt.business(business_id) as conn:
        return business_info(conn).currency


def _item(record: InboxRecord, currency: str) -> InboxItem:
    return InboxItem(record=record, facts=record_facts(record, currency))


@router.get("/businesses/{business_id}/inbox", response_model=InboxList)
def list_inbox(business_id: BusinessId, rt: RuntimeDep) -> InboxList:
    """Processed messages, newest first, with sentinel flags, risk and any verification call script."""
    currency = _currency(rt, business_id)
    records = list(reversed(store_for(rt, business_id).all()))
    return InboxList(total=len(records), held=sum(r.sentinel.hold for r in records),
                     items=[_item(r, currency) for r in records])


@router.post("/businesses/{business_id}/inbox/sync", response_model=InboxSyncResult)
def sync_inbox(business_id: BusinessId, rt: RuntimeDep) -> InboxSyncResult:
    """Deliver and process new mailbox messages (quarantined extractor, then the sentinel, then the forecast feed)."""
    proc = InboxProcessor(rt, business_id)
    report = proc.sync()
    held = [e for e in report.processed if (r := proc.store.get(e)) and r.sentinel.hold]
    return InboxSyncResult(processed=report.processed, skipped_existing=report.skipped_existing,
                           not_yet_delivered=report.not_yet_delivered, failed=report.failed, held=held)


@router.post("/businesses/{business_id}/inbox/upload", response_model=InboxItem)
async def upload_email(business_id: BusinessId, rt: RuntimeDep, file: UploadFile = File(...)) -> InboxItem:
    """Process one uploaded .eml message through the same quarantine and sentinel path."""
    data = await file.read(MAX_EMAIL_BYTES + 1)
    if len(data) > MAX_EMAIL_BYTES:
        raise HTTPException(413, "email too large")
    try:
        record = InboxProcessor(rt, business_id).upload(data)
    except EmailParseError as exc:
        raise HTTPException(422, str(exc)) from exc
    return _item(record, _currency(rt, business_id))


@router.get("/businesses/{business_id}/inbox/{email_id}", response_model=InboxDetail)
def inbox_detail(business_id: BusinessId, email_id: str, rt: RuntimeDep) -> InboxDetail:
    record = store_for(rt, business_id).get(email_id)
    path = raw_path(rt, business_id, email_id) if record else None
    if record is None or path is None:
        raise HTTPException(404, "no such inbox item")
    raw = parse_email(email_id, path.read_bytes())
    hidden = list(raw.html_hidden_text)
    for a in raw.attachments:
        if a.kind == "pdf":
            hidden += [r.text for r in extract_pdf_text(a.data).hidden_runs]
    return InboxDetail(item=_item(record, _currency(rt, business_id)), body_text=raw.body_text, hidden_text=hidden)
