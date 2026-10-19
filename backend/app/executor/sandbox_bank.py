"""Sandbox bank: simulated payments, payee changes, rescheduled payments and cancelled subscriptions.
Never calls a real bank.

Invariant 1: import only from app.gateway. tests/unit/test_executor_imports.py fails if anything else imports it.
Every method trusts its caller completely, which is why only the gateway, after policy and signature checks, may
reach it.
"""

import json
import sqlite3
import threading
from datetime import date
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS operations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,
    on_date TEXT NOT NULL,
    details TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS payee_accounts (payee_id TEXT PRIMARY KEY, account_token TEXT NOT NULL);
"""


class SandboxBank:
    def __init__(self, path: Path | str):
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        self._lock = threading.Lock()
        self._conn.executescript(SCHEMA)

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def _record(self, kind: str, today: date, details: dict) -> dict:
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO operations (kind, on_date, details) VALUES (?,?,?)",
                (kind, today.isoformat(), json.dumps(details, sort_keys=True)),
            )
        return {"sandbox_ref": f"sbx_{kind}_{cur.lastrowid:06d}", "kind": kind, **details}

    def pay(self, payee_id: str, amount_minor: int, reference: str, today: date) -> dict:
        if not isinstance(amount_minor, int) or amount_minor <= 0:
            raise ValueError("amount_minor must be a positive integer")
        return self._record("payment", today, {"payee_id": payee_id, "amount_minor": amount_minor,
                                               "reference": reference})

    def change_payee(self, payee_id: str, account_token: str, today: date) -> dict:
        with self._lock:
            self._conn.execute("INSERT OR REPLACE INTO payee_accounts VALUES (?, ?)", (payee_id, account_token))
        return self._record("payee_change", today, {"payee_id": payee_id, "account_token": account_token})

    def reschedule_payment(self, payment_ref: str, new_date: str, today: date) -> dict:
        date.fromisoformat(new_date)
        return self._record("reschedule", today, {"payment_ref": payment_ref, "new_date": new_date})

    def cancel_subscription(self, subscription_id: str, today: date) -> dict:
        return self._record("cancel_subscription", today, {"subscription_id": subscription_id})

    def operations(self) -> list[dict]:
        rows = self._conn.execute("SELECT id, kind, on_date, details FROM operations ORDER BY id").fetchall()
        return [{"id": r[0], "kind": r[1], "on_date": r[2], **json.loads(r[3])} for r in rows]

    def payee_account(self, payee_id: str) -> str | None:
        row = self._conn.execute("SELECT account_token FROM payee_accounts WHERE payee_id = ?", (payee_id,))
        found = row.fetchone()
        return found[0] if found else None
