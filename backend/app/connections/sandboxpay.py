"""SandboxPay (the simulated payment provider): the per-business connection record, the consent flow (authorization
code + PKCE + state), token exchange and revocation, and the route the gateway's executor pays through.

- The provider issues a scoped bearer token for the scopes and caps the owner approved on its own consent screen,
  plus a per-connection webhook secret. Both are stored encrypted (connections/crypto.py) at
  data_dir/<business_id>/sandboxpay.sqlite, never returned by the API, logged or shown to the planner.
- Sending a payment is not here: it is app/executor/sandbox_bank.py, reachable only through the gateway
  (invariant 1). `PaymentRoute` is what the gateway hands that executor: the token, and the payee accounts on file.
- Disconnect revokes the token at the provider first, then deletes it here.
"""

import sqlite3
import urllib.parse
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from app.connections.crypto import TokenCipher
from app.connections.http import Response, Transport, TransportError

SCOPES: tuple[str, ...] = ("payments.send", "payments.read")


class ProviderError(RuntimeError):
    """The provider refused or could not be reached. `code` is its error identifier or `unreachable`."""

    def __init__(self, code: str, status: int = 0):
        super().__init__(code)
        self.code, self.status = code, status


def error_of(res: Response) -> ProviderError:
    body = res.body if isinstance(res.body, dict) else {}
    return ProviderError(str(body.get("error") or res.status), res.status)


@dataclass(frozen=True)
class Connection:
    connection_id: str
    token_enc: bytes
    webhook_secret_enc: bytes
    scopes: tuple[str, ...]
    per_payment_cap_minor: int
    daily_cap_minor: int
    currency: str
    account_name: str
    connected_on: date


_DDL = """
CREATE TABLE IF NOT EXISTS connection (
    id INTEGER PRIMARY KEY CHECK (id = 1), connection_id TEXT NOT NULL, token_enc BLOB NOT NULL,
    webhook_secret_enc BLOB NOT NULL, scopes TEXT NOT NULL, per_payment_cap_minor INTEGER NOT NULL,
    daily_cap_minor INTEGER NOT NULL, currency TEXT NOT NULL, account_name TEXT NOT NULL, connected_on TEXT NOT NULL
);
"""


class ConnectionStore:
    """One business's SandboxPay connection (at most one)."""

    def __init__(self, path: Path):
        self.path = path

    def _run(self, fn):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path)
        try:
            conn.executescript(_DDL)
            with conn:
                return fn(conn)
        finally:
            conn.close()

    def get(self) -> Connection | None:
        if not self.path.is_file():
            return None
        row = self._run(lambda c: c.execute(
            "SELECT connection_id, token_enc, webhook_secret_enc, scopes, per_payment_cap_minor, daily_cap_minor,"
            " currency, account_name, connected_on FROM connection WHERE id = 1").fetchone())
        if row is None:
            return None
        return Connection(row[0], bytes(row[1]), bytes(row[2]), tuple(row[3].split()), row[4], row[5], row[6], row[7],
                          date.fromisoformat(row[8]))

    def save(self, c: Connection) -> None:
        self._run(lambda conn: conn.execute(
            "INSERT OR REPLACE INTO connection VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (c.connection_id, c.token_enc, c.webhook_secret_enc, " ".join(c.scopes), c.per_payment_cap_minor,
             c.daily_cap_minor, c.currency, c.account_name, c.connected_on.isoformat())))

    def delete(self) -> None:
        if self.path.is_file():
            self._run(lambda conn: conn.execute("DELETE FROM connection"))


def authorize_url(public_url: str, client_id: str, redirect_uri: str, state: str, challenge: str, *,
                  per_payment_cap: int, daily_cap: int, currency: str, client_name: str, account_name: str) -> str:
    return public_url.rstrip("/") + "/authorize?" + urllib.parse.urlencode({
        "client_id": client_id, "redirect_uri": redirect_uri, "state": state, "code_challenge": challenge,
        "code_challenge_method": "S256", "scope": " ".join(SCOPES), "per_payment_cap": per_payment_cap,
        "daily_cap": daily_cap, "currency": currency, "client_name": client_name, "account_name": account_name,
    })


@dataclass(frozen=True)
class ProviderClient:
    """Consent-time and status calls to the provider (no payments: those are the executor's)."""

    base_url: str
    transport: Transport

    def _call(self, method: str, path: str, **kwargs) -> dict:
        try:
            res = self.transport.request(method, self.base_url.rstrip("/") + path, **kwargs)
        except TransportError:
            raise ProviderError("unreachable") from None
        if not res.ok or not isinstance(res.body, dict):
            raise error_of(res)
        return res.body

    def exchange(self, client_id: str, client_secret: str, code: str, verifier: str, redirect_uri: str,
                 webhook_url: str) -> dict:
        return self._call("POST", "/oauth/token", json_body={
            "client_id": client_id, "client_secret": client_secret, "code": code, "code_verifier": verifier,
            "redirect_uri": redirect_uri, "webhook_url": webhook_url})

    def revoke(self, token: str) -> bool:
        return bool(self._call("POST", "/oauth/revoke", json_body={"token": token}).get("revoked"))

    def connection(self, token: str) -> dict:
        return self._call("GET", "/v1/connection", headers={"Authorization": f"Bearer {token}"})


@dataclass(frozen=True)
class ProviderAccess:
    """What the executor needs to send one payment: where, with which token, in which currency."""

    base_url: str
    token: str
    currency: str
    transport: Transport


class PaymentRoute:
    """How the gateway's payment executor reaches the provider and knows each payee's account on file.

    `access()` is None when no provider is connected (or its token cannot be decrypted): a payment then fails as
    `not_connected` and nothing is sent. `account_on_file(payee_id)` and `payee_name(payee_id)` read the business's
    own contact book, never an email. `check_request(args)` is the Payments service's rule for a request that
    came from a Sentinel-flagged email (call-script verification first) and for args that no longer match the
    request it was approved for; None means no objection.
    """

    def __init__(self, store: ConnectionStore, cipher: Callable[[], TokenCipher], base_url: str, transport: Transport,
                 accounts: Callable[[], dict[str, tuple[str, str]]],
                 check_request: Callable[[dict], str | None] = lambda _args: None):
        self.store, self._cipher, self.base_url, self.transport = store, cipher, base_url, transport
        self._accounts, self.check_request = accounts, check_request

    def access(self) -> ProviderAccess | None:
        c = self.store.get()
        if c is None:
            return None
        try:
            token = self._cipher().decrypt(c.token_enc)
        except Exception:  # noqa: BLE001 - a missing or changed key means: not connected
            return None
        return ProviderAccess(self.base_url, token, c.currency, self.transport)

    def account_on_file(self, payee_id: str) -> str | None:
        found = self._accounts().get(payee_id)
        return found[1] if found else None

    def payee_name(self, payee_id: str) -> str:
        found = self._accounts().get(payee_id)
        return found[0] if found else payee_id
