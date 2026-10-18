"""Per-tenant SQLite: one file per business under data/tenants/<business_id>.sqlite.

Tables
  meta          business_id, currency, schema_version, pii_key (HMAC key for PII tokens; see ledger/pii.py)
  accounts      one row per statement account; id is the PII token of the account number
  imports       one row per ingested statement file (sha256 of the file bytes)
  transactions  signed amount_minor (+ money in, - money out) in the tenant currency
  scheduled_items  known upcoming payables/receivables (rent, payroll, customer dues) for the forecast;
                   amount_minor is unsigned, kind gives the direction; counterparty_id is a stable
                   counterparty ID (e.g. sup_ggw), not PII
  pii_vault     token -> raw phone / national ID / account number

Free text (description, counterparty, reference) is stored with PII already replaced by tokens. It is still
untrusted text from an uploaded file and must never be passed to the planner (invariant 2); the planner gets row
IDs, categories and Facts only.
"""

import re
import secrets
import sqlite3
from pathlib import Path

from app.ledger.money import exponent

SCHEMA_VERSION = 1
BUSINESS_ID = re.compile(r"[a-z0-9][a-z0-9-]{1,62}")

DDL = """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS accounts (
    id       TEXT PRIMARY KEY,
    name     TEXT NOT NULL,
    currency TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS imports (
    id          TEXT PRIMARY KEY,
    account_id  TEXT NOT NULL REFERENCES accounts(id),
    source_name TEXT NOT NULL,
    file_sha256 TEXT NOT NULL,
    row_count   INTEGER NOT NULL,
    inserted    INTEGER NOT NULL,
    duplicates  INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS transactions (
    id                TEXT PRIMARY KEY,
    account_id        TEXT NOT NULL REFERENCES accounts(id),
    posted_on         TEXT NOT NULL CHECK (posted_on GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
    amount_minor      INTEGER NOT NULL CHECK (typeof(amount_minor) = 'integer'),
    currency          TEXT NOT NULL,
    description       TEXT NOT NULL,
    counterparty      TEXT,
    counterparty_ref  TEXT,
    reference         TEXT,
    channel           TEXT,
    category          TEXT,
    balance_minor     INTEGER CHECK (balance_minor IS NULL OR typeof(balance_minor) = 'integer'),
    import_id         TEXT NOT NULL REFERENCES imports(id),
    source_line       INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_transactions_posted_on ON transactions(posted_on);
CREATE TABLE IF NOT EXISTS scheduled_items (
    id               TEXT PRIMARY KEY,
    kind             TEXT NOT NULL CHECK (kind IN ('payable', 'receivable')),
    category         TEXT NOT NULL,
    due_date         TEXT NOT NULL CHECK (due_date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
    amount_minor     INTEGER NOT NULL CHECK (typeof(amount_minor) = 'integer' AND amount_minor > 0),
    status           TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'paid')),
    counterparty_id  TEXT,
    reference        TEXT,
    source           TEXT
);
CREATE INDEX IF NOT EXISTS ix_scheduled_due ON scheduled_items(due_date);
CREATE TABLE IF NOT EXISTS pii_vault (
    token TEXT PRIMARY KEY,
    kind  TEXT NOT NULL,
    value TEXT NOT NULL,
    UNIQUE (kind, value)
);
"""


class TenantError(ValueError):
    """Bad business ID, unknown tenant, or a tenant file that does not match this schema."""


def tenant_path(data_dir: Path, business_id: str) -> Path:
    """Path of a business's SQLite file. The ID is a strict slug, so it cannot escape data_dir."""
    if not BUSINESS_ID.fullmatch(business_id):
        raise TenantError(f"invalid business id {business_id!r}")
    return data_dir / f"{business_id}.sqlite"


def connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def create_tenant(path: Path, business_id: str, currency: str, pii_key: bytes | None = None) -> sqlite3.Connection:
    """Create a tenant DB. pii_key defaults to 32 random bytes; pass a fixed key only for deterministic seeds."""
    if not BUSINESS_ID.fullmatch(business_id):
        raise TenantError(f"invalid business id {business_id!r}")
    exponent(currency)  # unsupported currency fails here, not at first ingest
    if path.exists():
        raise TenantError(f"tenant already exists: {path.name}")
    key = pii_key if pii_key is not None else secrets.token_bytes(32)
    if len(key) < 16:
        raise TenantError("pii_key must be at least 16 bytes")
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = connect(path)
    with conn:
        conn.executescript(DDL)
        conn.executemany(
            "INSERT INTO meta (key, value) VALUES (?, ?)",
            [
                ("schema_version", str(SCHEMA_VERSION)),
                ("business_id", business_id),
                ("currency", currency),
                ("pii_key", key.hex()),
            ],
        )
    return conn


def open_tenant(path: Path) -> sqlite3.Connection:
    if not path.exists():
        raise TenantError(f"no such tenant: {path.name}")
    conn = connect(path)
    version = get_meta(conn, "schema_version")
    if version != str(SCHEMA_VERSION):
        conn.close()
        raise TenantError(f"{path.name} has schema version {version}, expected {SCHEMA_VERSION}")
    return conn


def get_meta(conn: sqlite3.Connection, key: str) -> str | None:
    try:
        row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    except sqlite3.OperationalError:
        return None
    return row["value"] if row else None
