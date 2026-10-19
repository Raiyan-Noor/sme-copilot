"""Gateway state in one SQLite file per business: owner public keys, used nonces, signed mandates, pending
approvals and the execution history used for frequency caps.

Security-relevant properties:
- Only public keys are stored (invariant 6).
- A nonce is consumed by an INSERT on a primary key, so a replay fails atomically even under concurrency.
- Every stored mandate keeps its canonical-JSON hash; `mandates_since()` hands new ones to anchoring (invariant 9).
"""

import json
import sqlite3
import threading
from datetime import date
from pathlib import Path

from app.audit.canonical import canonical_hash
from app.gateway.mandate import MandateRecord, SignedPayload, StandingTerms, mandate_document

SCHEMA = """
CREATE TABLE IF NOT EXISTS owner_keys (public_key TEXT PRIMARY KEY, enrolled_on TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS nonces (nonce TEXT PRIMARY KEY, used_on TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS mandates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,
    action TEXT NOT NULL,
    expiry TEXT NOT NULL,
    document TEXT NOT NULL,
    record_hash TEXT NOT NULL,
    signed_on TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS approvals (
    id TEXT PRIMARY KEY,
    tool TEXT NOT NULL,
    args TEXT NOT NULL,
    payload TEXT NOT NULL,
    reasons TEXT NOT NULL,
    status TEXT NOT NULL,
    created_on TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS executions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tool TEXT NOT NULL,
    key TEXT,
    on_date TEXT NOT NULL,
    mandate_id INTEGER
);
"""


class Approval:
    def __init__(self, id: str, tool: str, args: dict, payload: SignedPayload, reasons: list[str], status: str):
        self.id, self.tool, self.args, self.payload, self.reasons, self.status = id, tool, args, payload, reasons, status


class GatewayStore:
    def __init__(self, path: Path | str):
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        self._lock = threading.Lock()
        self._conn.executescript(SCHEMA)

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # Owner keys
    def enroll_key(self, public_key_hex: str, today: date) -> None:
        bytes.fromhex(public_key_hex)
        if len(public_key_hex) != 64:
            raise ValueError("Ed25519 public key must be 32 bytes hex")
        with self._lock:
            self._conn.execute(
                "INSERT OR IGNORE INTO owner_keys VALUES (?, ?)", (public_key_hex.lower(), today.isoformat())
            )

    def has_owner_key(self) -> bool:
        """True once any owner key is enrolled (the API enrolls trust-on-first-use)."""
        return self._conn.execute("SELECT 1 FROM owner_keys LIMIT 1").fetchone() is not None

    def is_enrolled(self, public_key_hex: str) -> bool:
        row = self._conn.execute("SELECT 1 FROM owner_keys WHERE public_key = ?", (public_key_hex.lower(),))
        return row.fetchone() is not None

    # Nonces
    def consume_nonce(self, nonce: str, today: date) -> bool:
        """Mark `nonce` used. False if it was already used (a replay)."""
        try:
            with self._lock:
                self._conn.execute("INSERT INTO nonces VALUES (?, ?)", (nonce, today.isoformat()))
            return True
        except sqlite3.IntegrityError:
            return False

    def nonce_used(self, nonce: str) -> bool:
        return self._conn.execute("SELECT 1 FROM nonces WHERE nonce = ?", (nonce,)).fetchone() is not None

    # Mandates
    def add_mandate(
        self,
        kind: str,
        payload: SignedPayload,
        signature: str,
        public_key: str,
        terms: StandingTerms | None,
        today: date,
    ) -> MandateRecord:
        doc = mandate_document(kind, payload, signature, public_key, terms)
        record_hash = canonical_hash(doc)
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO mandates (kind, action, expiry, document, record_hash, signed_on) VALUES (?,?,?,?,?,?)",
                (kind, payload.action, payload.expiry.isoformat(), json.dumps(doc), record_hash, today.isoformat()),
            )
        return self._record(cur.lastrowid, kind, doc, record_hash, today.isoformat())

    @staticmethod
    def _record(id: int, kind: str, doc: dict, record_hash: str, signed_on: str) -> MandateRecord:
        return MandateRecord(
            id=id,
            kind=kind,
            payload=SignedPayload(**doc["payload"]),
            signature=doc["signature"],
            public_key=doc["public_key"],
            terms=StandingTerms(**doc["terms"]) if "terms" in doc else None,
            signed_on=date.fromisoformat(signed_on),
            record_hash=record_hash,
        )

    def _select_mandates(self, where: str, params: tuple) -> list[MandateRecord]:
        rows = self._conn.execute(
            f"SELECT id, kind, document, record_hash, signed_on FROM mandates WHERE {where} ORDER BY id", params
        ).fetchall()
        return [self._record(r[0], r[1], json.loads(r[2]), r[3], r[4]) for r in rows]

    def active_standing(self, action: str, today: date) -> MandateRecord | None:
        """The most recently signed standing mandate for `action` that has not expired."""
        found = self._select_mandates(
            "kind = 'standing' AND action = ? AND expiry >= ?", (action, today.isoformat())
        )
        return found[-1] if found else None

    def mandates_since(self, after_id: int = 0) -> list[MandateRecord]:
        """Mandates stored after `after_id`, oldest first. Anchoring batches their `record_hash` values."""
        return self._select_mandates("id > ?", (after_id,))

    def mandate_document(self, mandate_id: int) -> tuple[dict, str] | None:
        """The stored document of a mandate exactly as saved, and the hash recorded when it was signed. Anchoring
        recomputes the hash from this document, so an edit to the row shows up as a mismatch (invariant 9)."""
        row = self._conn.execute("SELECT document, record_hash FROM mandates WHERE id = ?", (mandate_id,)).fetchone()
        return (json.loads(row[0]), row[1]) if row else None

    # Approvals
    def add_approval(self, approval: Approval, today: date) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO approvals VALUES (?,?,?,?,?,?,?)",
                (
                    approval.id,
                    approval.tool,
                    json.dumps(approval.args, sort_keys=True),
                    approval.payload.model_dump_json(),
                    json.dumps(approval.reasons),
                    approval.status,
                    today.isoformat(),
                ),
            )

    def get_approval(self, approval_id: str) -> Approval | None:
        row = self._conn.execute(
            "SELECT id, tool, args, payload, reasons, status FROM approvals WHERE id = ?", (approval_id,)
        ).fetchone()
        if row is None:
            return None
        return Approval(
            row[0], row[1], json.loads(row[2]), SignedPayload.model_validate_json(row[3]), json.loads(row[4]), row[5]
        )

    def pending_approvals(self, today: date) -> list[Approval]:
        """Approvals still waiting for the owner's signature whose payload has not expired, oldest first."""
        rows = self._conn.execute(
            "SELECT id, tool, args, payload, reasons, status FROM approvals WHERE status = 'pending'"
            " ORDER BY created_on, id"
        ).fetchall()
        found = [Approval(r[0], r[1], json.loads(r[2]), SignedPayload.model_validate_json(r[3]), json.loads(r[4]),
                          r[5]) for r in rows]
        return [a for a in found if a.payload.expiry >= today]

    def set_approval_status(self, approval_id: str, status: str) -> None:
        with self._lock:
            self._conn.execute("UPDATE approvals SET status = ? WHERE id = ?", (status, approval_id))

    # Executions
    def record_execution(self, tool: str, key: str | None, today: date, mandate_id: int | None) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO executions (tool, key, on_date, mandate_id) VALUES (?,?,?,?)",
                (tool, key, today.isoformat(), mandate_id),
            )

    def executions_since(self, tool: str, key: str, since: date) -> int:
        """Executions of `tool` for `key` on or after `since`."""
        row = self._conn.execute(
            "SELECT COUNT(*) FROM executions WHERE tool = ? AND key = ? AND on_date >= ?",
            (tool, key, since.isoformat()),
        ).fetchone()
        return row[0]
