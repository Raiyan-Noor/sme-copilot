"""Ledger transactions and CSV statement upload.

Transaction text (description, counterparty, reference) is shown to the owner here with PII already tokenized; it
is untrusted content and never goes to the planner (invariant 2).
"""

import asyncio
import csv
import io
from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.api.deps import BusinessId, RuntimeDep
from app.ledger.ingest import IngestReport, RowError, StatementError, ingest_statement
from app.ledger.snapshot import LedgerSnapshot, load_snapshot
from app.packs.ledger_view import categorize_snapshot
from app.services.businesses import business_pack

router = APIRouter(tags=["ledger"])

MAX_STATEMENT_BYTES = 5 * 1024 * 1024

# Rows come from a bank/wallet statement import, or from a payment that settled through the Payments tab (its import
# ID is `pay_<request>`; services/payments.py posts it only on the provider's signed "settled" webhook). Both are
# settled; the quarantined extractor's approval flow may later add "pending" ones.
TransactionSource = Literal["import", "payment"]
TransactionStatus = Literal["settled"]


class TransactionRow(BaseModel):
    """A ledger row as shown to the owner: the raw row plus what the tab needs that the row alone doesn't carry."""

    id: str
    account_id: str
    posted_on: date
    amount_minor: int
    currency: str
    description: str
    counterparty: str | None = None
    counterparty_ref: str | None = None
    reference: str | None = None
    channel: str | None = None
    category: str | None = None
    balance_minor: int | None = None  # as reported by the statement, if any; may differ from running_balance_minor
    running_balance_minor: int  # cumulative sum of amount_minor across every account, oldest first
    import_id: str
    source_line: int
    source: TransactionSource = "import"
    status: TransactionStatus = "settled"


class TransactionPage(BaseModel):
    pack_ref: str  # transactions are categorized by this pack
    total: int
    offset: int
    limit: int
    items: list[TransactionRow]


class StatementRejected(BaseModel):
    message: str
    errors: list[RowError]


class StatementRejectedResponse(BaseModel):
    detail: StatementRejected


def _row(t, running: dict[str, int]) -> "TransactionRow":
    return TransactionRow(**t.model_dump(), running_balance_minor=running[t.id],
                          source="payment" if t.import_id.startswith("pay_") else "import")


def _running_balances(snapshot: LedgerSnapshot) -> dict[str, int]:
    """Cumulative amount_minor across every account, in the snapshot's chronological order."""
    running = 0
    out: dict[str, int] = {}
    for t in snapshot.transactions:
        running += t.amount_minor
        out[t.id] = running
    return out


def _rows(
    snapshot: LedgerSnapshot,
    running: dict[str, int],
    *,
    date_from: date | None = None,
    date_to: date | None = None,
    category: str | None = None,
    account_id: str | None = None,
    search: str | None = None,
    direction: Literal["in", "out"] | None = None,
) -> list[TransactionRow]:
    needle = search.strip().lower() if search else None
    out = []
    for t in snapshot.transactions:
        if date_from is not None and t.posted_on < date_from:
            continue
        if date_to is not None and t.posted_on > date_to:
            continue
        if category is not None and t.category != category:
            continue
        if account_id is not None and t.account_id != account_id:
            continue
        if direction == "in" and t.amount_minor < 0:
            continue
        if direction == "out" and t.amount_minor >= 0:
            continue
        if needle and needle not in t.description.lower() and needle not in (t.counterparty or "").lower():
            continue
        out.append(_row(t, running))
    return out


def _load_rows(rt: RuntimeDep, business_id: str, **filters) -> tuple[str, list[TransactionRow]]:
    with rt.business(business_id) as conn:
        pack = business_pack(conn)
        snapshot = categorize_snapshot(load_snapshot(conn), pack)
        return pack.ref, _rows(snapshot, _running_balances(snapshot), **filters)


@router.get("/businesses/{business_id}/transactions", response_model=TransactionPage)
def get_transactions(
    business_id: BusinessId,
    rt: RuntimeDep,
    date_from: date | None = None,
    date_to: date | None = None,
    category: str | None = None,
    account_id: str | None = None,
    search: Annotated[str | None, Query(max_length=200, description="Matches description or counterparty")] = None,
    direction: Literal["in", "out"] | None = None,
    order: Literal["asc", "desc"] = "desc",
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> TransactionPage:
    """Ledger rows, categorized by the active Skill Pack. Amounts are signed integer minor units."""
    pack_ref, rows = _load_rows(rt, business_id, date_from=date_from, date_to=date_to, category=category,
                               account_id=account_id, search=search, direction=direction)
    if order == "desc":
        rows.reverse()
    return TransactionPage(pack_ref=pack_ref, total=len(rows), offset=offset, limit=limit,
                           items=rows[offset:offset + limit])


CSV_COLUMNS = ["posted_on", "description", "counterparty", "category", "amount_minor", "currency",
              "running_balance_minor", "source", "status", "account_id", "id"]


@router.get(
    "/businesses/{business_id}/transactions/export",
    response_class=StreamingResponse,
    responses={200: {"content": {"text/csv": {}}, "description": "The filtered view as CSV"}},
)
def export_transactions(
    business_id: BusinessId,
    rt: RuntimeDep,
    date_from: date | None = None,
    date_to: date | None = None,
    category: str | None = None,
    account_id: str | None = None,
    search: Annotated[str | None, Query(max_length=200)] = None,
    direction: Literal["in", "out"] | None = None,
    order: Literal["asc", "desc"] = "desc",
) -> StreamingResponse:
    """The current filtered view as CSV, exactly as shown (no re-fetch needed to match what the owner sees)."""
    _pack_ref, rows = _load_rows(rt, business_id, date_from=date_from, date_to=date_to, category=category,
                                 account_id=account_id, search=search, direction=direction)
    if order == "desc":
        rows.reverse()
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=CSV_COLUMNS, extrasaction="ignore")
    writer.writeheader()
    for r in rows:
        writer.writerow({**r.model_dump(mode="json")})
    rt.audit.append("ledger.transactions_exported", {"business_id": business_id, "rows": len(rows)})
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition": 'attachment; filename="transactions.csv"'})


async def _transaction_events(rt: RuntimeDep, business_id: str, request: Request, *, poll_seconds: float = 1.5):
    """New rows since the connection opened, as SSE frames. A plain generator so tests can drive it directly
    instead of fighting a test client that buffers streaming responses to completion.
    """
    with rt.business(business_id) as conn:
        seen_ids = {t.id for t in load_snapshot(conn).transactions}
    while True:
        if await request.is_disconnected():
            break
        with rt.business(business_id) as conn:
            pack = business_pack(conn)
            snapshot = categorize_snapshot(load_snapshot(conn), pack)
        new_ids = {t.id for t in snapshot.transactions} - seen_ids
        if new_ids:
            running = _running_balances(snapshot)
            seen_ids |= new_ids
            for t in snapshot.transactions:
                if t.id in new_ids:
                    row = _row(t, running)
                    yield f"event: transaction\ndata: {row.model_dump_json()}\n\n"
            yield f"event: balance\ndata: {running[snapshot.transactions[-1].id]}\n\n"
        await asyncio.sleep(poll_seconds)


@router.get(
    "/businesses/{business_id}/transactions/stream",
    response_class=StreamingResponse,
    responses={200: {"content": {"text/event-stream": {}},
                     "description": "Server-sent events: a `transaction` event per new row since the connection "
                                    "opened, from a statement import or (once built) a settled payment."}},
)
def stream_transactions(business_id: BusinessId, request: Request, rt: RuntimeDep) -> StreamingResponse:
    """Poll the ledger's version (already the engine's fact-cache key) and push any newly inserted rows.

    No new write path or broadcaster: a new row only ever arrives through the existing ingest/execution code, which
    bumps `ledger_version`. Polling keeps this endpoint simple and side-effect free if nobody is listening.
    """
    return StreamingResponse(_transaction_events(rt, business_id, request), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("/businesses/{business_id}/transactions/{row_id}", response_model=TransactionRow)
def get_transaction(business_id: BusinessId, row_id: str, rt: RuntimeDep) -> TransactionRow:
    """One row, for the detail drawer. 404 if no such row (e.g. a stale link into a different business)."""
    _pack_ref, rows = _load_rows(rt, business_id)
    row = next((r for r in rows if r.id == row_id), None)
    if row is None:
        raise HTTPException(404, f"no such transaction: {row_id}")
    return row


@router.post(
    "/businesses/{business_id}/statements",
    response_model=IngestReport,
    responses={422: {"model": StatementRejectedResponse, "description": "Statement rejected; nothing was written"}},
)
async def upload_statement(
    business_id: BusinessId,
    rt: RuntimeDep,
    file: Annotated[UploadFile, File(description="CSV statement (UTF-8)")],
    account_number: Annotated[str, Form(min_length=1, max_length=64, description="Tokenized before storage")],
    account_name: Annotated[str, Form(max_length=120)] = "Statement account",
    decimal_sep: Annotated[Literal[".", ","], Form()] = ".",
    date_format: Annotated[Literal["%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%d.%m.%Y"], Form()] = "%Y-%m-%d",
) -> IngestReport:
    """Ingest a CSV statement for one account. All rows or none; re-uploading the same rows adds no duplicates."""
    data = await file.read(MAX_STATEMENT_BYTES + 1)
    if len(data) > MAX_STATEMENT_BYTES:
        raise HTTPException(413, f"statement larger than {MAX_STATEMENT_BYTES} bytes")
    with rt.business(business_id) as conn:
        try:
            report = ingest_statement(conn, data, source_name=file.filename or "statement.csv",
                                      account_number=account_number, account_name=account_name,
                                      decimal_sep=decimal_sep, date_format=date_format)
        except StatementError as e:
            rt.audit.append("ledger.statement_rejected", {"business_id": business_id, "errors": len(e.errors)})
            raise HTTPException(422, StatementRejected(message="statement rejected; nothing was written",
                                                       errors=e.errors).model_dump()) from None
    rt.audit.append("ledger.statement_ingested", {"business_id": business_id, **report.model_dump(mode="json")})
    return report
