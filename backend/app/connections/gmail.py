"""Gmail over OAuth: the per-business connection record, the authorization-code flow with PKCE, and a read-only
API client. Sending lives in app/executor/gmail_sender.py, reachable only through the gateway (invariant 1).

- Scopes: gmail.readonly and gmail.send, nothing else.
- The refresh token is stored encrypted (connections/crypto.py), per business, at data_dir/<business_id>/gmail.sqlite.
  It never leaves the server: the API returns only the connected address and status, and nothing here is visible to
  the planner (invariant 2: mail content goes only to the quarantined extractor, through services/inbox.py).
- Every request is logged by the caller as an audit event without tokens, secrets or message text (invariant 7).
"""

import base64
import hashlib
import secrets
import sqlite3
import urllib.parse
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Literal

from app.connections.http import Response, Transport, TransportError

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
API_URL = "https://gmail.googleapis.com/gmail/v1/users/me"
SCOPES: tuple[str, ...] = (
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
)
MAX_HISTORY_PAGES = 5
MAX_IMPORT = 25

ConnectionState = Literal["connected", "reconnect_needed", "unreachable"]
InboxSource = Literal["gmail", "sandbox"]


class GmailError(RuntimeError):
    """A Gmail or Google OAuth failure. `retry`: transient (rate limit, 5xx, network), back off and try again.
    `reauth`: the grant is gone (revoked, expired, wrong scopes); the owner has to reconnect."""

    def __init__(self, code: str, *, retry: bool = False, reauth: bool = False):
        super().__init__(code)
        self.code = code
        self.retry = retry
        self.reauth = reauth


def _classify(res: Response) -> GmailError:
    code = res.error_code()
    if res.status == 429 or res.status >= 500 or code in ("rateLimitExceeded", "userRateLimitExceeded"):
        return GmailError(code, retry=True)
    if code in ("invalid_grant", "unauthorized_client", "invalid_client") or res.status in (401, 403):
        return GmailError(code, reauth=True)
    return GmailError(code)


# ---- Connection record ---------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class Connection:
    email_address: str
    refresh_token_enc: bytes
    scopes: tuple[str, ...]
    history_id: str | None
    connected_on: date
    state: ConnectionState
    last_error: str | None


_DDL = """
CREATE TABLE IF NOT EXISTS connection (
    id                INTEGER PRIMARY KEY CHECK (id = 1),
    email_address     TEXT NOT NULL,
    refresh_token_enc BLOB NOT NULL,
    scopes            TEXT NOT NULL,
    history_id        TEXT,
    connected_on      TEXT NOT NULL,
    state             TEXT NOT NULL,
    last_error        TEXT
);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


class ConnectionStore:
    """One business's Gmail connection (at most one) and its inbox source switch."""

    def __init__(self, path: Path):
        self.path = path

    def _conn(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path)
        conn.executescript(_DDL)
        return conn

    def _run(self, fn):
        conn = self._conn()
        try:
            with conn:
                return fn(conn)
        finally:
            conn.close()

    def get(self) -> Connection | None:
        if not self.path.is_file():
            return None
        row = self._run(lambda c: c.execute(
            "SELECT email_address, refresh_token_enc, scopes, history_id, connected_on, state, last_error "
            "FROM connection WHERE id = 1").fetchone())
        if row is None:
            return None
        return Connection(row[0], bytes(row[1]), tuple(row[2].split()), row[3], date.fromisoformat(row[4]),
                          row[5], row[6])

    def save(self, c: Connection) -> None:
        self._run(lambda conn: conn.execute(
            "INSERT OR REPLACE INTO connection VALUES (1, ?, ?, ?, ?, ?, ?, ?)",
            (c.email_address, c.refresh_token_enc, " ".join(c.scopes), c.history_id, c.connected_on.isoformat(),
             c.state, c.last_error)))

    def update(self, **fields) -> None:
        allowed = {"history_id", "state", "last_error"}
        assert set(fields) <= allowed, fields
        cols = ", ".join(f"{k} = ?" for k in fields)
        self._run(lambda conn: conn.execute(f"UPDATE connection SET {cols} WHERE id = 1", tuple(fields.values())))

    def delete(self) -> None:
        if self.path.is_file():
            self._run(lambda conn: conn.execute("DELETE FROM connection"))

    def source(self) -> InboxSource:
        if not self.path.is_file():
            return "sandbox"
        row = self._run(lambda c: c.execute("SELECT value FROM settings WHERE key = 'source'").fetchone())
        return "gmail" if row and row[0] == "gmail" else "sandbox"

    def set_source(self, source: InboxSource) -> None:
        self._run(lambda c: c.execute("INSERT OR REPLACE INTO settings VALUES ('source', ?)", (source,)))


# ---- OAuth (authorization code + PKCE) -----------------------------------------------------------------------------

def pkce_pair() -> tuple[str, str]:
    """(code_verifier, S256 code_challenge), RFC 7636."""
    verifier = secrets.token_urlsafe(64)[:96]
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


def authorize_url(client_id: str, redirect_uri: str, state: str, challenge: str) -> str:
    return AUTH_URL + "?" + urllib.parse.urlencode({
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(SCOPES),
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "access_type": "offline",  # a refresh token, so polling survives the hour-long access token
        "prompt": "consent",  # always return a refresh token, even when this account consented before
        "include_granted_scopes": "false",
    })


@dataclass(frozen=True)
class Grant:
    access_token: str
    expires_in: int
    refresh_token: str | None
    scopes: tuple[str, ...]


class GoogleOAuth:
    def __init__(self, client_id: str, client_secret: str, redirect_uri: str, transport: Transport):
        self.client_id = client_id
        self._secret = client_secret
        self.redirect_uri = redirect_uri
        self.http = transport

    def _token(self, form: dict[str, str]) -> Grant:
        try:
            res = self.http.request("POST", TOKEN_URL, form={
                "client_id": self.client_id, "client_secret": self._secret, **form})
        except TransportError as exc:
            raise GmailError(f"network:{exc}", retry=True) from None
        if not res.ok or not isinstance(res.body, dict) or "access_token" not in res.body:
            raise _classify(res)
        b = res.body
        return Grant(str(b["access_token"]), int(b.get("expires_in") or 3600), b.get("refresh_token"),
                     tuple(str(b.get("scope") or "").split()))

    def exchange(self, code: str, verifier: str) -> Grant:
        return self._token({"grant_type": "authorization_code", "code": code, "code_verifier": verifier,
                            "redirect_uri": self.redirect_uri})

    def refresh(self, refresh_token: str) -> Grant:
        return self._token({"grant_type": "refresh_token", "refresh_token": refresh_token})

    def revoke(self, token: str) -> bool:
        try:
            return self.http.request("POST", REVOKE_URL, form={"token": token}).ok
        except TransportError:
            return False


# ---- Read-only API -------------------------------------------------------------------------------------------------

class GmailReader:
    """gmail.readonly calls only. `token(force)` returns a valid access token (forcing a refresh after a 401)."""

    def __init__(self, transport: Transport, token: Callable[[bool], str]):
        self.http = transport
        self.token = token

    def _get(self, path: str, params: dict[str, str] | None = None) -> dict:
        url = f"{API_URL}/{path}" + ("?" + urllib.parse.urlencode(params, doseq=True) if params else "")
        for attempt in (0, 1):
            try:
                res = self.http.request("GET", url, headers={"Authorization": f"Bearer {self.token(attempt == 1)}"})
            except TransportError as exc:
                raise GmailError(f"network:{exc}", retry=True) from None
            if res.status == 401 and attempt == 0:
                continue  # access token expired early: refresh once
            if res.status == 404:
                raise GmailError("not_found")
            if not res.ok or not isinstance(res.body, dict):
                raise _classify(res)
            return res.body
        raise GmailError("unauthorized", reauth=True)

    def profile(self) -> tuple[str, str]:
        b = self._get("profile")
        return str(b["emailAddress"]).lower(), str(b["historyId"])

    def new_inbox_messages(self, start_history_id: str) -> tuple[list[str], str]:
        """Message IDs added to the inbox since `start_history_id`, oldest first, and the new history ID.
        Raises GmailError("not_found") when the history ID is too old (the caller resets from the profile)."""
        ids: list[str] = []
        params = {"startHistoryId": start_history_id, "historyTypes": "messageAdded", "labelId": "INBOX"}
        latest = start_history_id
        for _ in range(MAX_HISTORY_PAGES):
            b = self._get("history", params)
            latest = str(b.get("historyId") or latest)
            for h in b.get("history", []):
                for added in h.get("messagesAdded", []):
                    mid = str((added.get("message") or {}).get("id") or "")
                    if mid and mid not in ids:
                        ids.append(mid)
            if not b.get("nextPageToken"):
                break
            params = {**params, "pageToken": str(b["nextPageToken"])}
        return ids, latest

    def recent_inbox_messages(self, days: int) -> list[str]:
        b = self._get("messages", {"q": f"in:inbox newer_than:{int(days)}d", "maxResults": str(MAX_IMPORT)})
        return list(reversed([str(m["id"]) for m in b.get("messages", []) if m.get("id")]))

    def raw_message(self, message_id: str) -> tuple[bytes, tuple[str, ...]]:
        """The full RFC 822 message (headers, body, attachments) and its labels."""
        b = self._get(f"messages/{urllib.parse.quote(message_id, safe='')}", {"format": "raw"})
        raw = base64.urlsafe_b64decode(str(b.get("raw") or "") + "==")
        return raw, tuple(str(x) for x in b.get("labelIds", []))


# ---- What the gateway's mail executor is given ---------------------------------------------------------------------

@dataclass(frozen=True)
class Recipient:
    name: str
    email: str | None


@dataclass(frozen=True)
class GmailSendAccess:
    """Enough to send one message as the connected account: built by the runtime, used only by the executor."""

    from_address: str
    token: Callable[[], str]
    transport: Transport


@dataclass(frozen=True)
class MailRoute:
    """How the gateway's mail executor reaches this business's contacts. `gmail()` is None unless Gmail is connected,
    healthy and the active inbox; `allowlist` is DEMO_SEND_ALLOWLIST (real sends go only to those addresses)."""

    business_name: Callable[[], str]
    recipient: Callable[[str], Recipient | None]
    gmail: Callable[[], GmailSendAccess | None]
    allowlist: frozenset[str]
