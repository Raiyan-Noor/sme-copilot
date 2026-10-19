"""Inbox: quarantined email processing and the Inbox Sentinel's findings, for the owner's Inbox screen.

The owner may see raw message text (detail view); the planner never does (invariant 2). Amounts and dates are
returned as Facts (invariant 4) built from the typed fields, with the inbox item as their source.
"""

import asyncio
from typing import Annotated

from fastapi import APIRouter, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import StreamingResponse
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


async def _inbox_events(rt, business_id: str, request: Request, after: int | None, *, poll_seconds: float = 0.5):
    """Inbox events after `after` (default: from now) as SSE frames. A plain generator so tests can drive it."""
    seq = rt.inbox_events.latest() if after is None else after
    while not await request.is_disconnected():
        for event in rt.inbox_events.since(business_id, seq):
            seq = event.seq
            yield f"id: {event.seq}\nevent: {event.kind}\ndata: {event.model_dump_json()}\n\n"
        await asyncio.sleep(poll_seconds)


@router.get(
    "/businesses/{business_id}/inbox/stream",
    response_class=StreamingResponse,
    responses={200: {"content": {"text/event-stream": {}},
                     "description": "Server-sent events: `message` (one email's stage: received, extracting, "
                                    "checking, then accepted, flagged, held or failed) and `connection` (the Gmail "
                                    "connection's new status)."}},
)
def stream_inbox(business_id: BusinessId, request: Request, rt: RuntimeDep,
                 after: Annotated[int | None, Query(ge=0)] = None) -> StreamingResponse:
    """Live progress of mail through quarantine and the sentinel, from Gmail, the sandbox mailbox or an upload."""
    with rt.business(business_id):
        pass
    return StreamingResponse(_inbox_events(rt, business_id, request, after), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


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
