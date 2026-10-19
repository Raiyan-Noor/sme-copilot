"""SandboxPay's core: OAuth-style consent and scoped tokens, payments with idempotency keys, its own limits, and
asynchronous settlement reported by signed webhooks.

What the provider enforces on its own, whatever the client asks for:
- A token works only for the scopes and caps the owner approved on the consent screen (the owner may lower the
  caps the client asked for, never raise them), and only until it is revoked.
- Per-payment cap and daily cap (sum of today's non-failed payments, UTC day of the provider's own clock).
- Idempotency: one `Idempotency-Key` is one payment. A retry with the same key and body returns the same payment; the
  same key with a different body is refused (409). A double click can never pay twice.
- Webhooks go only to the URL registered when the token was issued, signed with HMAC-SHA256 over the raw body with a
  per-connection secret.

Tokens and codes are stored only as SHA-256 hashes. Money is integer minor units.
"""

import hashlib
import hmac
import json
import secrets
import sqlite3
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

SCOPES = ("payments.send", "payments.read")
CODE_TTL_S = 300
WEBHOOK_ATTEMPTS = 4

SCHEMA = """
CREATE TABLE IF NOT EXISTS codes (
    code_hash TEXT PRIMARY KEY, client_id TEXT NOT NULL, redirect_uri TEXT NOT NULL, challenge TEXT NOT NULL,
    scopes TEXT NOT NULL, per_payment_cap INTEGER NOT NULL, daily_cap INTEGER NOT NULL, currency TEXT NOT NULL,
    account_name TEXT NOT NULL, expires_at REAL NOT NULL, used INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS connections (
    id TEXT PRIMARY KEY, token_hash TEXT NOT NULL UNIQUE, client_id TEXT NOT NULL, scopes TEXT NOT NULL,
    per_payment_cap INTEGER NOT NULL, daily_cap INTEGER NOT NULL, currency TEXT NOT NULL, account_name TEXT NOT NULL,
    webhook_url TEXT NOT NULL, webhook_secret TEXT NOT NULL, created_at REAL NOT NULL, revoked_at REAL
);
CREATE TABLE IF NOT EXISTS payments (
    id TEXT PRIMARY KEY, connection_id TEXT NOT NULL, idempotency_key TEXT NOT NULL, request_hash TEXT NOT NULL,
    payee_ref TEXT NOT NULL, payee_name TEXT NOT NULL, account_token TEXT NOT NULL, amount_minor INTEGER NOT NULL,
    currency TEXT NOT NULL, reference TEXT NOT NULL, status TEXT NOT NULL, failure_reason TEXT,
    created_at REAL NOT NULL, settle_at REAL NOT NULL, settled_at REAL, webhook_attempts INTEGER NOT NULL DEFAULT 0,
    webhook_delivered INTEGER NOT NULL DEFAULT 0, next_webhook_at REAL,
    UNIQUE (connection_id, idempotency_key)
);
"""


class ProviderError(Exception):
    """A refused request: HTTP status and a machine-readable error code."""

    def __init__(self, status: int, code: str, detail: str = ""):
        super().__init__(code)
        self.status, self.code, self.detail = status, code, detail or code


@dataclass
class ProviderConfig:
    client_id: str
    client_secret: str
    redirect_uris: tuple[str, ...]
    webhook_prefixes: tuple[str, ...]
    settle_seconds: float = 4.0
    fail_accounts: frozenset[str] = frozenset()


@dataclass
class Connection:
    id: str
    client_id: str
    scopes: tuple[str, ...]
    per_payment_cap: int
    daily_cap: int
    currency: str
    account_name: str
    webhook_url: str
    webhook_secret: str
    revoked_at: float | None


def _h(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _challenge(verifier: str) -> str:
    import base64

    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()


def sign_body(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def _day_start(now: float) -> float:
    d = datetime.fromtimestamp(now, timezone.utc)
    return datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp()


Poster = Callable[[str, bytes, dict[str, str]], int]


def urllib_post(url: str, body: bytes, headers: dict[str, str]) -> int:
    import urllib.error
    import urllib.request

    req = urllib.request.Request(url, data=body, headers={**headers, "Content-Type": "application/json"},
                                 method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as res:
            return res.status
    except urllib.error.HTTPError as exc:
        return exc.code
    except (urllib.error.URLError, TimeoutError, OSError):
        return 0


@dataclass
class SandboxPay:
    path: Path | str
    config: ProviderConfig
    post: Poster = urllib_post
    now: Callable[[], float] = time.time
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def __post_init__(self) -> None:
        if str(self.path) != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA)

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # ---- Consent and tokens -----------------------------------------------------------------------------------

    def check_authorize(self, client_id: str, redirect_uri: str, scope: str, per_payment_cap: int,
                        daily_cap: int) -> tuple[str, ...]:
        if client_id != self.config.client_id:
            raise ProviderError(400, "unknown_client")
        if redirect_uri not in self.config.redirect_uris:
            raise ProviderError(400, "redirect_uri_not_registered")
        scopes = tuple(s for s in scope.split() if s)
        if not scopes or any(s not in SCOPES for s in scopes):
            raise ProviderError(400, "invalid_scope")
        if per_payment_cap <= 0 or daily_cap <= 0 or per_payment_cap > daily_cap:
            raise ProviderError(400, "invalid_limits")
        return scopes

    def approve(self, *, client_id: str, redirect_uri: str, scope: str, challenge: str, requested_per_payment: int,
                requested_daily: int, per_payment_cap: int, daily_cap: int, currency: str,
                account_name: str) -> str:
        """The owner approved the consent screen. Returns a one-time code. Caps may be lowered, never raised."""
        scopes = self.check_authorize(client_id, redirect_uri, scope, requested_per_payment, requested_daily)
        if not (0 < per_payment_cap <= requested_per_payment and 0 < daily_cap <= requested_daily
                and per_payment_cap <= daily_cap):
            raise ProviderError(400, "invalid_limits", "limits may be lowered, not raised")
        if not challenge:
            raise ProviderError(400, "pkce_required")
        code = secrets.token_urlsafe(24)
        with self._lock:
            self._conn.execute(
                "INSERT INTO codes VALUES (?,?,?,?,?,?,?,?,?,?,0)",
                (_h(code), client_id, redirect_uri, challenge, " ".join(scopes), per_payment_cap, daily_cap,
                 currency.upper()[:3], account_name[:80], self.now() + CODE_TTL_S))
        return code

    def exchange(self, *, client_id: str, client_secret: str, code: str, code_verifier: str, redirect_uri: str,
                 webhook_url: str) -> dict:
        if client_id != self.config.client_id or not self.config.client_secret or not hmac.compare_digest(
                client_secret.encode(), self.config.client_secret.encode()):
            raise ProviderError(401, "invalid_client")
        if not any(webhook_url.startswith(p) for p in self.config.webhook_prefixes):
            raise ProviderError(400, "webhook_url_not_allowed")
        with self._lock:
            row = self._conn.execute("SELECT * FROM codes WHERE code_hash = ?", (_h(code),)).fetchone()
            if row is None or row["used"] or row["expires_at"] < self.now():
                raise ProviderError(400, "invalid_grant")
            if row["redirect_uri"] != redirect_uri or row["client_id"] != client_id:
                raise ProviderError(400, "invalid_grant")
            if not hmac.compare_digest(_challenge(code_verifier), row["challenge"]):
                raise ProviderError(400, "invalid_grant", "PKCE verifier does not match")
            self._conn.execute("UPDATE codes SET used = 1 WHERE code_hash = ?", (_h(code),))
            token, secret = "spt_" + secrets.token_urlsafe(32), "whsec_" + secrets.token_urlsafe(24)
            cid = "con_" + secrets.token_hex(8)
            self._conn.execute(
                "INSERT INTO connections VALUES (?,?,?,?,?,?,?,?,?,?,?,NULL)",
                (cid, _h(token), client_id, row["scopes"], row["per_payment_cap"], row["daily_cap"], row["currency"],
                 row["account_name"], webhook_url, secret, self.now()))
        return {"access_token": token, "token_type": "bearer", "connection_id": cid, "scope": row["scopes"],
                "per_payment_cap_minor": row["per_payment_cap"], "daily_cap_minor": row["daily_cap"],
                "currency": row["currency"], "account_name": row["account_name"], "webhook_secret": secret}

    def revoke(self, token: str) -> bool:
        with self._lock:
            cur = self._conn.execute("UPDATE connections SET revoked_at = ? WHERE token_hash = ? AND revoked_at IS NULL",
                                     (self.now(), _h(token)))
        return cur.rowcount > 0

    def connection(self, token: str | None) -> Connection:
        if not token:
            raise ProviderError(401, "missing_token")
        row = self._conn.execute("SELECT * FROM connections WHERE token_hash = ?", (_h(token),)).fetchone()
        if row is None:
            raise ProviderError(401, "invalid_token")
        if row["revoked_at"] is not None:
            raise ProviderError(401, "token_revoked")
        return Connection(row["id"], row["client_id"], tuple(row["scopes"].split()), row["per_payment_cap"],
                          row["daily_cap"], row["currency"], row["account_name"], row["webhook_url"],
                          row["webhook_secret"], row["revoked_at"])

    def spent_today(self, connection_id: str) -> int:
        row = self._conn.execute(
            "SELECT COALESCE(SUM(amount_minor), 0) FROM payments WHERE connection_id = ? AND status != 'failed'"
            " AND created_at >= ?", (connection_id, _day_start(self.now()))).fetchone()
        return int(row[0])

    def connection_view(self, token: str | None) -> dict:
        c = self.connection(token)
        return {"connection_id": c.id, "scopes": list(c.scopes), "per_payment_cap_minor": c.per_payment_cap,
                "daily_cap_minor": c.daily_cap, "currency": c.currency, "account_name": c.account_name,
                "spent_today_minor": self.spent_today(c.id)}

    # ---- Payments ---------------------------------------------------------------------------------------------

    def create_payment(self, token: str | None, idempotency_key: str | None, body: dict) -> tuple[int, dict]:
        c = self.connection(token)
        if "payments.send" not in c.scopes:
            raise ProviderError(403, "insufficient_scope")
        key = (idempotency_key or "").strip()
        if not (8 <= len(key) <= 128):
            raise ProviderError(400, "idempotency_key_required")
        try:
            payee_ref, payee_name = str(body["payee_ref"])[:64], str(body.get("payee_name") or "")[:80]
            account, reference = str(body["account_token"])[:128], str(body.get("reference") or "")[:64]
            amount, currency = body["amount_minor"], str(body["currency"]).upper()
        except (KeyError, TypeError):
            raise ProviderError(422, "invalid_request") from None
        if isinstance(amount, bool) or not isinstance(amount, int) or amount <= 0:
            raise ProviderError(422, "invalid_amount")
        if currency != c.currency:
            raise ProviderError(422, "currency_mismatch")
        request_hash = _h(json.dumps([payee_ref, account, amount, currency, reference]))
        with self._lock:
            found = self._conn.execute("SELECT * FROM payments WHERE connection_id = ? AND idempotency_key = ?",
                                       (c.id, key)).fetchone()
            if found is not None:
                if found["request_hash"] != request_hash:
                    raise ProviderError(409, "idempotency_conflict", "this key was used for a different payment")
                return 200, self._view(found)
            if amount > c.per_payment_cap:
                raise ProviderError(403, "over_per_payment_cap")
            if self.spent_today(c.id) + amount > c.daily_cap:
                raise ProviderError(403, "over_daily_cap")
            pid = "pmt_" + secrets.token_hex(8)
            now = self.now()
            self._conn.execute(
                "INSERT INTO payments (id, connection_id, idempotency_key, request_hash, payee_ref, payee_name,"
                " account_token, amount_minor, currency, reference, status, created_at, settle_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,'processing',?,?)",
                (pid, c.id, key, request_hash, payee_ref, payee_name, account, amount, currency, reference, now,
                 now + self.config.settle_seconds))
            row = self._conn.execute("SELECT * FROM payments WHERE id = ?", (pid,)).fetchone()
        return 202, self._view(row)

    def get_payment(self, token: str | None, payment_id: str) -> dict:
        c = self.connection(token)
        row = self._conn.execute("SELECT * FROM payments WHERE id = ? AND connection_id = ?",
                                 (payment_id, c.id)).fetchone()
        if row is None:
            raise ProviderError(404, "no_such_payment")
        return self._view(row)

    @staticmethod
    def _view(row: sqlite3.Row) -> dict:
        return {"id": row["id"], "status": row["status"], "idempotency_key": row["idempotency_key"],
                "payee_ref": row["payee_ref"], "amount_minor": row["amount_minor"], "currency": row["currency"],
                "reference": row["reference"], "failure_reason": row["failure_reason"],
                "created_at": row["created_at"], "settled_at": row["settled_at"]}

    # ---- Settlement and webhooks ------------------------------------------------------------------------------

    def settle_due(self, force: bool = False) -> list[str]:
        """Settle (or fail) every processing payment whose settlement time has come, then send webhooks."""
        now = self.now()
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, account_token FROM payments WHERE status = 'processing'" + ("" if force else
                                                                                       " AND settle_at <= ?"),
                () if force else (now,)).fetchall()
            for r in rows:
                failed = r["account_token"] in self.config.fail_accounts
                self._conn.execute(
                    "UPDATE payments SET status = ?, failure_reason = ?, settled_at = ?, next_webhook_at = ?"
                    " WHERE id = ?", ("failed" if failed else "settled", "account_closed" if failed else None, now,
                                      now, r["id"]))
        self.deliver_webhooks()
        return [r["id"] for r in rows]

    def deliver_webhooks(self) -> None:
        now = self.now()
        rows = self._conn.execute(
            "SELECT p.*, c.webhook_url, c.webhook_secret FROM payments p JOIN connections c ON c.id = p.connection_id"
            " WHERE p.status IN ('settled', 'failed') AND p.webhook_delivered = 0 AND p.webhook_attempts < ?"
            " AND p.next_webhook_at <= ?", (WEBHOOK_ATTEMPTS, now)).fetchall()
        for r in rows:
            event = {"type": f"payment.{r['status']}", "payment": self._view(r), "connection_id": r["connection_id"],
                     "sent_at": now}
            body = json.dumps(event, sort_keys=True).encode()
            status = self.post(r["webhook_url"], body, {"X-SandboxPay-Signature": sign_body(r["webhook_secret"], body),
                                                        "X-SandboxPay-Event": event["type"]})
            ok = 200 <= status < 300
            attempts = r["webhook_attempts"] + 1
            with self._lock:
                self._conn.execute(
                    "UPDATE payments SET webhook_attempts = ?, webhook_delivered = ?, next_webhook_at = ? WHERE id = ?",
                    (attempts, int(ok), now + 2 ** attempts, r["id"]))

    def run_forever(self, stop: threading.Event, interval: float = 0.5) -> None:
        while not stop.wait(interval):
            try:
                self.settle_due()
            except sqlite3.Error:
                pass
