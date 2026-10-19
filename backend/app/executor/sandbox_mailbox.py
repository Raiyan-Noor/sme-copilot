"""Sandbox mailbox: simulated outbound messages (reminders, supplier messages, draft loan applications).
Never sends real email.

Invariant 1: import only from app.gateway.
"""

import json
import sqlite3
import threading
from datetime import date
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS outbox (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,
    recipient_id TEXT NOT NULL,
    on_date TEXT NOT NULL,
    details TEXT NOT NULL
);
"""


class SandboxMailbox:
    def __init__(self, path: Path | str):
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        self._lock = threading.Lock()
        self._conn.executescript(SCHEMA)

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def send(self, kind: str, recipient_id: str, details: dict, today: date) -> dict:
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO outbox (kind, recipient_id, on_date, details) VALUES (?,?,?,?)",
                (kind, recipient_id, today.isoformat(), json.dumps(details, sort_keys=True)),
            )
        return {"sandbox_ref": f"sbx_mail_{cur.lastrowid:06d}", "kind": kind, "recipient_id": recipient_id,
                **details}

    def outbox(self) -> list[dict]:
        rows = self._conn.execute("SELECT id, kind, recipient_id, on_date, details FROM outbox ORDER BY id")
        return [{"id": r[0], "kind": r[1], "recipient_id": r[2], "on_date": r[3], **json.loads(r[4])}
                for r in rows.fetchall()]
