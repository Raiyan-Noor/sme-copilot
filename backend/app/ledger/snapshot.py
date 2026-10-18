"""Read-only ledger snapshot: the input to every engine function `(ledger snapshot, pack, clock) -> list[Fact]`.

Text fields carry tokens instead of PII but are still untrusted file content (invariant 2): engine code may read
them to classify rows; nothing may forward them to the planner.
"""

import sqlite3
from datetime import date

from pydantic import BaseModel, ConfigDict

from app.ledger.schema import get_meta


class Transaction(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    account_id: str
    posted_on: date
    amount_minor: int  # + money in, - money out, tenant currency
    currency: str
    description: str
    counterparty: str | None = None
    counterparty_ref: str | None = None  # PII token of the counterparty's account or phone
    reference: str | None = None
    channel: str | None = None
    category: str | None = None
    balance_minor: int | None = None
    import_id: str
    source_line: int


class LedgerSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)

    business_id: str
    currency: str
    transactions: tuple[Transaction, ...]

    def by_id(self) -> dict[str, Transaction]:
        return {t.id: t for t in self.transactions}


def load_snapshot(conn: sqlite3.Connection) -> LedgerSnapshot:
    """All transactions in statement order (date, then import, then line), so engine output is deterministic."""
    rows = conn.execute(
        "SELECT * FROM transactions ORDER BY posted_on, import_id, source_line, id"
    ).fetchall()
    return LedgerSnapshot(
        business_id=get_meta(conn, "business_id") or "",
        currency=get_meta(conn, "currency") or "",
        transactions=tuple(Transaction.model_validate(dict(r)) for r in rows),
    )
