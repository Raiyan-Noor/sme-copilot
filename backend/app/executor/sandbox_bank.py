"""Sandbox bank: the client for SandboxPay (the simulated payment provider, a separate local service), plus simulated
payee changes, rescheduled payments and cancelled subscriptions. Never calls a real bank.

Invariant 1: import only from app.gateway. tests/unit/test_executor_imports.py fails if anything else imports it.
Every method trusts its caller completely, which is why only the gateway, after policy and signature checks, may
reach it.

Payments go to the provider over HTTP with an idempotency key: the Payments request ID for `pay_invoice`, or a hash of
payee, bill and amount for `pay_recurring_bill`. A key that was already accepted by the provider is never sent again
from here, and the provider itself refuses to pay one key twice, so a double click, a retry or a replay cannot pay
twice. The account paid is the one on file (the business's contact book, or a signed `change_payee_details`), never
one from an email. The provider answers "processing"; settlement arrives later by signed webhook (services/payments).
"""

import hashlib
import json
import sqlite3
import threading
from datetime import date
from pathlib import Path

from app.connections.http import TransportError
from app.connections.sandboxpay import PaymentRoute, error_of

SCHEMA = """
CREATE TABLE IF NOT EXISTS operations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,
    on_date TEXT NOT NULL,
    details TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS payee_accounts (payee_id TEXT PRIMARY KEY, account_token TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS sent_payments (
    idempotency_key TEXT PRIMARY KEY, operation_id INTEGER NOT NULL, provider_payment_id TEXT NOT NULL
);
"""


def bill_idempotency_key(payee_id: str, bill_id: str, amount_minor: int) -> str:
    """One bill, one payment: the same payee, bill and amount always produce the same key."""
    return "bill_" + hashlib.sha256(f"{payee_id}|{bill_id}|{amount_minor}".encode()).hexdigest()[:40]


class SandboxBank:
    def __init__(self, path: Path | str, route: PaymentRoute | None = None):
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        self._lock = threading.Lock()
        self._conn.executescript(SCHEMA)
        self.route = route

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

    def account_for(self, payee_id: str) -> str | None:
        """The account a payment to this payee goes to: a signed payee change, else the contact book's."""
        return self.payee_account(payee_id) or (self.route.account_on_file(payee_id) if self.route else None)

    def pay(self, payee_id: str, amount_minor: int, reference: str, today: date, *, account_token: str | None = None,
            idempotency_key: str | None = None, request_id: str | None = None) -> dict:
        if not isinstance(amount_minor, int) or isinstance(amount_minor, bool) or amount_minor <= 0:
            raise ValueError("amount_minor must be a positive integer")
        key = idempotency_key or bill_idempotency_key(payee_id, reference, amount_minor)
        done = self._conn.execute("SELECT operation_id, provider_payment_id FROM sent_payments WHERE "
                                  "idempotency_key = ?", (key,)).fetchone()
        if done is not None:  # already accepted by the provider: never send the same key twice
            return self._record("payment", today, {
                "payee_id": payee_id, "amount_minor": amount_minor, "reference": reference, "idempotency_key": key,
                "request_id": request_id, "provider_payment_id": done[1], "provider_status": "duplicate",
                "reason": f"already sent as operation {done[0]}"})
        account = account_token or self.account_for(payee_id)
        details = {"payee_id": payee_id, "amount_minor": amount_minor, "reference": reference, "idempotency_key": key,
                   "request_id": request_id, "provider_payment_id": None}
        access = self.route.access() if self.route else None
        if access is None:
            return self._record("payment", today, {**details, "provider_status": "not_sent",
                                                   "reason": "not_connected"})
        if account is None:
            return self._record("payment", today, {**details, "provider_status": "not_sent",
                                                   "reason": "no_account_on_file"})
        body = {"payee_ref": payee_id, "payee_name": self.route.payee_name(payee_id), "account_token": account,
                "amount_minor": amount_minor, "currency": access.currency, "reference": reference}
        headers = {"Authorization": f"Bearer {access.token}", "Idempotency-Key": key}
        res = None
        for _attempt in range(2):  # one retry on a network error is safe: the provider deduplicates by key
            try:
                res = access.transport.request("POST", access.base_url.rstrip("/") + "/v1/payments", headers=headers,
                                               json_body=body)
                break
            except TransportError:
                continue
        if res is None:
            return self._record("payment", today, {**details, "provider_status": "not_sent", "reason": "unreachable"})
        if not res.ok or not isinstance(res.body, dict) or not res.body.get("id"):
            return self._record("payment", today, {**details, "provider_status": "refused",
                                                   "reason": error_of(res).code})
        out = self._record("payment", today, {**details, "provider_payment_id": str(res.body["id"]),
                                              "provider_status": str(res.body.get("status") or "processing"),
                                              "reason": None})
        with self._lock:
            self._conn.execute("INSERT OR IGNORE INTO sent_payments VALUES (?, ?, ?)",
                               (key, int(out["sandbox_ref"].rsplit("_", 1)[-1]), out["provider_payment_id"]))
        return out

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
