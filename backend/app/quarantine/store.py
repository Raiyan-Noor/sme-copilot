"""Processed inbox items, one SQLite file per business at data_dir/<business_id>/inbox.sqlite.

A record holds the code-parsed headers, the typed fields, the owner-only view and the sentinel report. Raw bodies
and attachments are not copied here; the owner's detail view re-reads them from the source file.
"""

import sqlite3
from datetime import date, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from app.quarantine.typed import DocumentFields, OwnerView
from app.sentinel.checks import SentinelReport

FeedOutcome = Literal["scheduled", "already_scheduled", "past_due", "not_applicable", "held_by_sentinel",
                      "counterparty_unknown", "missing_fields"]


class AttachmentInfo(BaseModel):
    filename: str
    kind: str
    sha256: str
    extraction: str  # ok | invalid_output | unavailable | skipped
    hidden_runs: int = 0


class InboxRecord(BaseModel):
    email_id: str
    source: Literal["mailbox", "upload"]
    received_at: datetime | None
    received_on: date | None
    processed_on: date
    raw_sha256: str
    from_address: str
    from_display_name: str
    reply_to_address: str | None
    subject: str  # owner display only (invariant 2)
    auth: dict[str, str]
    attachments: list[AttachmentInfo]
    fields: DocumentFields
    owner_view: OwnerView
    sentinel: SentinelReport
    feed: FeedOutcome
    scheduled_item_ids: list[str] = []


_DDL = """
CREATE TABLE IF NOT EXISTS inbox_items (
    email_id     TEXT PRIMARY KEY,
    received_at  TEXT,
    record_json  TEXT NOT NULL
);
"""


class InboxStore:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        with self._conn() as conn:
            conn.executescript(_DDL)

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def has(self, email_id: str) -> bool:
        with self._conn() as conn:
            return conn.execute("SELECT 1 FROM inbox_items WHERE email_id = ?", (email_id,)).fetchone() is not None

    def put(self, record: InboxRecord) -> None:
        with self._conn() as conn:
            conn.execute("INSERT OR REPLACE INTO inbox_items (email_id, received_at, record_json) VALUES (?, ?, ?)",
                         (record.email_id, record.received_at.isoformat() if record.received_at else None,
                          record.model_dump_json()))

    def get(self, email_id: str) -> InboxRecord | None:
        with self._conn() as conn:
            row = conn.execute("SELECT record_json FROM inbox_items WHERE email_id = ?", (email_id,)).fetchone()
        return InboxRecord.model_validate_json(row["record_json"]) if row else None

    def all(self) -> list[InboxRecord]:
        """Oldest first."""
        with self._conn() as conn:
            rows = conn.execute("SELECT record_json FROM inbox_items ORDER BY received_at, email_id").fetchall()
        return [InboxRecord.model_validate_json(r["record_json"]) for r in rows]
