"""Payment requests, their status history, owner-added payees and call-script verifications: one SQLite file per
business at data_dir/<business_id>/payments.sqlite.

A request is the owner-facing record of one payment, from proposal to settlement. It is bookkeeping only: what
actually runs is decided by the gateway (invariant 1), and the gateway's own store keeps the signed approvals and
mandates. Statuses: proposed -> awaiting_approval -> approved -> sent -> settled | failed; or denied / cancelled.
"""

import json
import sqlite3
import threading
from datetime import date
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

PaymentStatus = Literal["proposed", "awaiting_approval", "approved", "sent", "settled", "failed", "denied", "cancelled"]
SourceKind = Literal["manual", "bill", "invoice", "email", "assistant"]
OPEN_STATUSES = ("proposed", "awaiting_approval", "approved", "sent", "settled")

_DDL = """
CREATE TABLE IF NOT EXISTS requests (
    id TEXT PRIMARY KEY, created_on TEXT NOT NULL, payee_id TEXT NOT NULL, payee_name TEXT NOT NULL,
    account_token TEXT, account_last4 TEXT, amount_minor INTEGER NOT NULL, currency TEXT NOT NULL,
    reference TEXT NOT NULL, reason TEXT NOT NULL, source_kind TEXT NOT NULL, source_ref TEXT, source_label TEXT NOT NULL,
    amount_untrusted INTEGER NOT NULL, scheduled_item_id TEXT, email_id TEXT, tool TEXT, bill_id TEXT,
    approval_id TEXT, mandate_id INTEGER, idempotency_key TEXT, provider_payment_id TEXT, status TEXT NOT NULL,
    rule TEXT, ledger_tx_id TEXT, receipt TEXT, receipt_sha256 TEXT, settled_on TEXT
);
CREATE INDEX IF NOT EXISTS ix_requests_provider ON requests(provider_payment_id);
CREATE TABLE IF NOT EXISTS events (
    seq INTEGER PRIMARY KEY AUTOINCREMENT, request_id TEXT NOT NULL, on_date TEXT NOT NULL, status TEXT NOT NULL,
    note TEXT
);
CREATE TABLE IF NOT EXISTS payees (
    id TEXT PRIMARY KEY, name TEXT NOT NULL, account_token TEXT NOT NULL, account_last4 TEXT NOT NULL,
    added_on TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS verifications (email_id TEXT PRIMARY KEY, verified_on TEXT NOT NULL);
"""


class PaymentEvent(BaseModel):
    seq: int
    on_date: date
    status: PaymentStatus
    note: str | None = None


class PaymentRequest(BaseModel):
    id: str
    created_on: date
    payee_id: str
    payee_name: str
    account_token: str | None = None
    account_last4: str | None = None
    amount_minor: int
    currency: str
    reference: str
    reason: str  # the owner's words or a code-written line; owner display only, never sent to the planner
    source_kind: SourceKind
    source_ref: str | None = None
    source_label: str
    amount_untrusted: bool  # the amount came from an email (invariant 3): always needs the owner's signature
    scheduled_item_id: str | None = None
    email_id: str | None = None
    tool: str | None = None
    bill_id: str | None = None
    approval_id: str | None = None
    mandate_id: int | None = None
    idempotency_key: str | None = None
    provider_payment_id: str | None = None
    status: PaymentStatus
    rule: str | None = None  # why it was denied or failed
    ledger_tx_id: str | None = None
    receipt_sha256: str | None = None
    settled_on: date | None = None


class OwnPayee(BaseModel):
    id: str
    name: str
    account_token: str
    account_last4: str
    added_on: date


_COLUMNS = list(PaymentRequest.model_fields)


class PaymentStore:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._lock = threading.Lock()
        with self._conn() as conn:
            conn.executescript(_DDL)

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def _write(self, sql: str, params: tuple) -> None:
        with self._lock:
            conn = self._conn()
            try:
                with conn:
                    conn.execute(sql, params)
            finally:
                conn.close()

    def _read(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        conn = self._conn()
        try:
            return conn.execute(sql, params).fetchall()
        finally:
            conn.close()

    # Requests
    def add(self, r: PaymentRequest) -> None:
        values = r.model_dump(mode="json")
        cols = ", ".join(_COLUMNS)
        self._write(f"INSERT INTO requests ({cols}, receipt) VALUES ({', '.join('?' * len(_COLUMNS))}, NULL)",
                    tuple(values[c] for c in _COLUMNS))

    def update(self, request_id: str, **fields) -> None:
        assert set(fields) <= set(_COLUMNS) | {"receipt"}, fields
        cols = ", ".join(f"{k} = ?" for k in fields)
        values = tuple(v.isoformat() if isinstance(v, date) else v for v in fields.values())
        self._write(f"UPDATE requests SET {cols} WHERE id = ?", (*values, request_id))

    def get(self, request_id: str) -> PaymentRequest | None:
        rows = self._read("SELECT * FROM requests WHERE id = ?", (request_id,))
        return PaymentRequest.model_validate({c: rows[0][c] for c in _COLUMNS}) if rows else None

    def receipt(self, request_id: str) -> dict | None:
        rows = self._read("SELECT receipt FROM requests WHERE id = ?", (request_id,))
        return json.loads(rows[0]["receipt"]) if rows and rows[0]["receipt"] else None

    def by_provider_payment(self, provider_payment_id: str) -> PaymentRequest | None:
        rows = self._read("SELECT id FROM requests WHERE provider_payment_id = ?", (provider_payment_id,))
        return self.get(rows[0]["id"]) if rows else None

    def by_bill(self, bill_id: str, statuses: tuple[str, ...]) -> PaymentRequest | None:
        marks = ", ".join("?" * len(statuses))
        rows = self._read(f"SELECT id FROM requests WHERE bill_id = ? AND status IN ({marks}) ORDER BY created_on DESC",
                          (bill_id, *statuses))
        return self.get(rows[0]["id"]) if rows else None

    def all(self) -> list[PaymentRequest]:
        """Newest first."""
        rows = self._read("SELECT * FROM requests ORDER BY created_on DESC, rowid DESC")
        return [PaymentRequest.model_validate({c: r[c] for c in _COLUMNS}) for r in rows]

    # Events
    def add_event(self, request_id: str, on_date: date, status: str, note: str | None = None) -> None:
        self._write("INSERT INTO events (request_id, on_date, status, note) VALUES (?, ?, ?, ?)",
                    (request_id, on_date.isoformat(), status, note))

    def events(self, request_id: str) -> list[PaymentEvent]:
        rows = self._read("SELECT seq, on_date, status, note FROM events WHERE request_id = ? ORDER BY seq",
                          (request_id,))
        return [PaymentEvent.model_validate(dict(r)) for r in rows]

    # Owner-added payees
    def add_payee(self, p: OwnPayee) -> None:
        self._write("INSERT INTO payees VALUES (?, ?, ?, ?, ?)",
                    (p.id, p.name, p.account_token, p.account_last4, p.added_on.isoformat()))

    def payees(self) -> list[OwnPayee]:
        return [OwnPayee.model_validate(dict(r)) for r in self._read("SELECT * FROM payees ORDER BY added_on, id")]

    # Call-script verifications for flagged emails
    def verify(self, email_id: str, on_date: date) -> None:
        self._write("INSERT OR REPLACE INTO verifications VALUES (?, ?)", (email_id, on_date.isoformat()))

    def verified(self, email_id: str) -> bool:
        return bool(self._read("SELECT 1 FROM verifications WHERE email_id = ?", (email_id,)))
