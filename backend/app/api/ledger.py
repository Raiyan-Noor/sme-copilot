"""Ledger transactions and CSV statement upload.

Transaction text (description, counterparty, reference) is shown to the owner here with PII already tokenized; it
is untrusted content and never goes to the planner (invariant 2).
"""

from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel

from app.api.deps import BusinessId, RuntimeDep
from app.ledger.ingest import IngestReport, RowError, StatementError, ingest_statement
from app.ledger.snapshot import Transaction, load_snapshot
from app.packs.ledger_view import categorize_snapshot
from app.services.businesses import business_pack

router = APIRouter(tags=["ledger"])

MAX_STATEMENT_BYTES = 5 * 1024 * 1024


class TransactionPage(BaseModel):
    pack_ref: str  # transactions are categorized by this pack
    total: int
    offset: int
    limit: int
    items: list[Transaction]


class StatementRejected(BaseModel):
    message: str
    errors: list[RowError]


class StatementRejectedResponse(BaseModel):
    detail: StatementRejected


@router.get("/businesses/{business_id}/transactions", response_model=TransactionPage)
def get_transactions(
    business_id: BusinessId,
    rt: RuntimeDep,
    date_from: date | None = None,
    date_to: date | None = None,
    category: str | None = None,
    account_id: str | None = None,
    order: Literal["asc", "desc"] = "desc",
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> TransactionPage:
    """Ledger rows, categorized by the active Skill Pack. Amounts are signed integer minor units."""
    with rt.business(business_id) as conn:
        pack = business_pack(conn)
        snapshot = categorize_snapshot(load_snapshot(conn), pack)
    rows = [t for t in snapshot.transactions
            if (date_from is None or t.posted_on >= date_from) and (date_to is None or t.posted_on <= date_to)
            and (category is None or t.category == category) and (account_id is None or t.account_id == account_id)]
    if order == "desc":
        rows.reverse()
    return TransactionPage(pack_ref=pack.ref, total=len(rows), offset=offset, limit=limit,
                           items=rows[offset:offset + limit])


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
