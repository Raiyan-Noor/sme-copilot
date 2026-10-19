"""The Gmail connection service: connect (OAuth code flow with PKCE and state), poll for new mail, import the last few
days on request, disconnect (revoke), and the mail route the gateway's executor sends with.

Security notes:
- Only the owner starts a connection (passcode-protected route). Google's redirect back is public, so it is accepted
  only with a one-time `state` that this server issued in the last ten minutes, bound to the business and to a PKCE
  verifier that never left the server.
- The refresh token is encrypted at rest (connections/crypto.py) and lives only in this service and the store; no
  route returns it and nothing reaches the planner (invariant 2). Audit entries carry the account's domain and a
  hash of its address, never tokens, secrets or message text (invariant 7).
- New mail goes through the same quarantine -> sentinel pipeline as the sandbox mailbox (services/inbox.py), raw
  RFC 822 message and attachments included. Only mail that arrives after connecting is processed, unless the owner
  asks to import the last 7 days.
- Transient Gmail failures (rate limits, 5xx, network) back off exponentially; a revoked or expired grant marks the
  connection "reconnect_needed". The sandbox inbox keeps working either way.

Wall-clock time here is `time.monotonic()`, only for OAuth state expiry, access-token lifetime and backoff: those
follow Google's real clock, not the simulated business date (clock.py stays the only source of business dates).
"""

import hashlib
import logging
import secrets
import threading
import time
from datetime import date
from typing import Literal

from pydantic import BaseModel

from app.connections.crypto import TokenCipher, TokenKeyMissing
from app.connections.gmail import (
    SCOPES, Connection, ConnectionStore, GmailError, GmailReader, GmailSendAccess, GoogleOAuth, InboxSource,
    FlaggedSenders, MailRoute, Recipient, authorize_url, pkce_pair,
)
from app.connections.http import Transport, UrllibTransport
from app.quarantine.mime import MAX_EMAIL_BYTES
from app.quarantine.store import InboxStore
from app.sentinel.directory import load_directory
from app.services.businesses import business_info, list_businesses, records_folder

log = logging.getLogger(__name__)

STATE_TTL_S = 600
MAX_BACKOFF_S = 300
RECENT_DAYS = 7

CAN_DO = [
    "Read new email that arrives after you connect, to spot invoices, payment requests and scams.",
    "Read attachments (PDF invoices, receipt photos) in quarantine, where nothing written in an email can make me act.",
    "Send an email from this address only after you approve it, or under a limit you signed, and only to your "
    "known contacts.",
]
CANNOT_DO = [
    "Delete, archive, label or change any of your email.",
    "See your Google password: Google handles the sign-in, and you can disconnect at any time.",
    "Read older email, unless you ask me to import the last 7 days.",
]

GmailState = Literal["not_configured", "disconnected", "connected", "reconnect_needed", "unreachable"]


class ConnectError(Exception):
    """A connect attempt failed; the message is plain language for the owner."""


class GmailStatus(BaseModel):
    configured: bool
    missing_settings: list[str]  # names of unset .env settings, never their values
    state: GmailState
    email_address: str | None
    connected_on: date | None
    source: InboxSource  # where new mail is read from and approved email is sent through
    message: str
    can_do: list[str]
    cannot_do: list[str]
    scopes: list[str]
    send_allowlist_count: int


def _account_hash(address: str) -> str:
    return hashlib.sha256(address.lower().encode()).hexdigest()[:16]


class GmailService:
    def __init__(self, rt, transport: Transport | None = None):
        self.rt = rt
        self.http: Transport = transport or UrllibTransport()
        self._lock = threading.RLock()
        self._pending: dict[str, tuple[str, str, float]] = {}  # state -> (business_id, PKCE verifier, issued at)
        self._tokens: dict[str, tuple[str, float]] = {}  # business_id -> (access token, expires at)
        self._backoff: dict[str, tuple[int, float]] = {}  # business_id -> (consecutive failures, next attempt)
        self._busy: set[str] = set()

    # ---- Configuration -------------------------------------------------------------------------------------------
    def missing_settings(self) -> list[str]:
        s = self.rt.settings
        missing = [name for name, value in (("GMAIL_CLIENT_ID", s.gmail_client_id),
                                            ("GMAIL_CLIENT_SECRET", s.gmail_client_secret.get_secret_value()))
                   if not value.strip()]
        try:
            TokenCipher(s.gmail_token_key.get_secret_value())
        except TokenKeyMissing:
            missing.append("GMAIL_TOKEN_KEY")
        return missing

    def _oauth(self) -> GoogleOAuth:
        s = self.rt.settings
        return GoogleOAuth(s.gmail_client_id, s.gmail_client_secret.get_secret_value(), s.gmail_redirect_uri,
                           self.http)

    def _cipher(self) -> TokenCipher:
        return TokenCipher(self.rt.settings.gmail_token_key.get_secret_value())

    def store(self, business_id: str) -> ConnectionStore:
        return ConnectionStore(self.rt.data_dir / business_id / "gmail.sqlite")

    # ---- Status --------------------------------------------------------------------------------------------------
    def status(self, business_id: str) -> GmailStatus:
        with self.rt.business(business_id):
            pass  # TenantError (404) for an unknown business
        missing = self.missing_settings()
        store = self.store(business_id)
        conn, source = store.get(), store.source()
        if conn is not None:
            state: GmailState = conn.state
            message = {
                "connected": f"Reading new mail from {conn.email_address}.",
                "reconnect_needed": "Gmail disconnected — reconnect. Your sandbox inbox keeps working meanwhile.",
                "unreachable": "Gmail is not answering right now; retrying. Your sandbox inbox keeps working.",
            }[conn.state]
            if conn.state == "connected" and source == "sandbox":
                message = f"Connected as {conn.email_address}, but paused: using the sandbox inbox."
        elif missing:
            state, message = "not_configured", "Gmail is not set up on this server yet."
        else:
            state, message = "disconnected", "Not connected. Using the sandbox inbox."
        return GmailStatus(
            configured=not missing, missing_settings=missing, state=state,
            email_address=conn.email_address if conn else None, connected_on=conn.connected_on if conn else None,
            source=source if conn else "sandbox", message=message, can_do=CAN_DO, cannot_do=CANNOT_DO,
            scopes=list(SCOPES), send_allowlist_count=len(self.rt.settings.send_allowlist))

    def _publish(self, business_id: str) -> None:
        self.rt.inbox_events.publish(business_id, kind="connection",
                                     connection=self.status(business_id).model_dump(mode="json"))

    # ---- Connect -------------------------------------------------------------------------------------------------
    def start(self, business_id: str) -> str:
        """The Google consent URL for this business. Issues a one-time state bound to a fresh PKCE verifier."""
        with self.rt.business(business_id):
            pass
        missing = self.missing_settings()
        if missing:
            raise ConnectError(f"Gmail is not set up on this server: set {', '.join(missing)} in .env.")
        state = secrets.token_urlsafe(32)
        verifier, challenge = pkce_pair()
        now = time.monotonic()
        with self._lock:
            self._pending = {k: v for k, v in self._pending.items() if now - v[2] < STATE_TTL_S}
            self._pending[state] = (business_id, verifier, now)
        self.rt.audit.append("gmail.connect_started", {"business_id": business_id, "scopes": list(SCOPES)})
        return authorize_url(self.rt.settings.gmail_client_id, self.rt.settings.gmail_redirect_uri, state, challenge)

    def finish(self, state: str | None, code: str | None, error: str | None) -> tuple[str, str]:
        """Complete the OAuth callback. Returns (business_id, connected address); raises ConnectError."""
        with self._lock:
            entry = self._pending.pop(state, None) if state else None
        if entry is None or time.monotonic() - entry[2] > STATE_TTL_S:
            self.rt.audit.append("gmail.connect_failed", {"business_id": entry[0] if entry else None,
                                                          "reason": "bad_state"})
            raise ConnectError("This sign-in was not started here, or it has expired. Start again from the app.")
        business_id, verifier, _ = entry

        def fail(reason: str, message: str) -> ConnectError:
            self.rt.audit.append("gmail.connect_failed", {"business_id": business_id, "reason": reason[:60]})
            return ConnectError(message)

        if error or not code:
            raise fail(error or "no_code", "Google sign-in was cancelled. Nothing was connected.")
        oauth = self._oauth()
        try:
            grant = oauth.exchange(code, verifier)
        except GmailError as exc:
            raise fail(f"exchange:{exc.code}", "Google did not accept the sign-in. Please try again.") from None
        if set(SCOPES) - set(grant.scopes) or not grant.refresh_token:
            oauth.revoke(grant.refresh_token or grant.access_token)
            raise fail("scopes" if set(SCOPES) - set(grant.scopes) else "no_refresh_token",
                       "Both permissions are needed (read and send). Connect again and allow both.")
        try:
            address, history_id = GmailReader(self.http, lambda _force: grant.access_token).profile()
        except GmailError as exc:
            oauth.revoke(grant.refresh_token)
            raise fail(f"profile:{exc.code}", "Connected to Google, but Gmail did not answer. Please try again.") \
                from None

        store = self.store(business_id)
        previous = store.get()
        cipher = self._cipher()
        if previous is not None:  # reconnecting: retire the old grant
            try:
                old = cipher.decrypt(previous.refresh_token_enc)
                if old != grant.refresh_token:
                    oauth.revoke(old)
            except TokenKeyMissing:
                pass
        store.save(Connection(address, cipher.encrypt(grant.refresh_token), SCOPES, history_id,
                              self.rt.clock.today(), "connected", None))
        store.set_source("gmail")
        with self._lock:
            self._tokens[business_id] = (grant.access_token, time.monotonic() + grant.expires_in)
            self._backoff.pop(business_id, None)
        self.rt.audit.append("gmail.connected", {
            "business_id": business_id, "account_domain": address.rsplit("@", 1)[-1],
            "account_sha256": _account_hash(address), "scopes": list(SCOPES), "reconnect": previous is not None})
        self._publish(business_id)
        return business_id, address

    def disconnect(self, business_id: str) -> GmailStatus:
        """Revoke the grant with Google (best effort) and delete it here; always ends disconnected."""
        store = self.store(business_id)
        conn = store.get()
        revoked = False
        if conn is not None:
            try:
                revoked = self._oauth().revoke(self._cipher().decrypt(conn.refresh_token_enc))
            except TokenKeyMissing:
                revoked = False
            store.delete()
            store.set_source("sandbox")
        with self._lock:
            self._tokens.pop(business_id, None)
            self._backoff.pop(business_id, None)
        if conn is not None:
            self.rt.audit.append("gmail.disconnected", {"business_id": business_id, "revoked": revoked,
                                                        "account_sha256": _account_hash(conn.email_address)})
            self._publish(business_id)
        return self.status(business_id)

    def set_source(self, business_id: str, source: InboxSource) -> GmailStatus:
        """The one-click switch: read (and send) through Gmail, or use the sandbox inbox."""
        store = self.store(business_id)
        conn = store.get()
        if source == "gmail" and conn is None:
            raise ConnectError("Connect Gmail first.")
        store.set_source(source)
        self.rt.audit.append("gmail.source_changed", {"business_id": business_id, "source": source})
        if source == "gmail" and conn is not None and conn.state != "connected":
            with self._lock:
                self._backoff.pop(business_id, None)  # try again right away
        self._publish(business_id)
        return self.status(business_id)

    # ---- Tokens --------------------------------------------------------------------------------------------------
    def access_token(self, business_id: str, force: bool = False) -> str:
        with self._lock:
            cached = self._tokens.get(business_id)
            if cached and not force and cached[1] - 60 > time.monotonic():
                return cached[0]
        conn = self.store(business_id).get()
        if conn is None:
            raise GmailError("not_connected", reauth=True)
        try:
            refresh = self._cipher().decrypt(conn.refresh_token_enc)
        except TokenKeyMissing:
            raise GmailError("token_key", reauth=True) from None
        grant = self._oauth().refresh(refresh)
        with self._lock:
            self._tokens[business_id] = (grant.access_token, time.monotonic() + grant.expires_in)
        return grant.access_token

    def reader(self, business_id: str) -> GmailReader:
        return GmailReader(self.http, lambda force: self.access_token(business_id, force))

    # ---- Reading mail --------------------------------------------------------------------------------------------
    def poll(self, business_id: str, *, wait: bool = False) -> list[str]:
        """Process mail that arrived since the last seen historyId. Returns the new inbox IDs. Skips quietly when
        not connected, paused, waiting out a backoff or already polling (unless `wait`)."""
        store = self.store(business_id)
        conn = store.get()
        if conn is None or conn.state == "reconnect_needed" or store.source() != "gmail":
            return []
        with self._lock:
            failures, next_at = self._backoff.get(business_id, (0, 0.0))
            if (not wait and time.monotonic() < next_at) or business_id in self._busy:
                return []
            self._busy.add(business_id)
        try:
            reader = self.reader(business_id)
            if conn.history_id is None:
                store.update(history_id=reader.profile()[1])
                return []
            try:
                ids, latest = reader.new_inbox_messages(conn.history_id)
            except GmailError as exc:
                if exc.code != "not_found":
                    raise
                latest = reader.profile()[1]  # history ID too old: start again from now
                self.rt.audit.append("gmail.history_reset", {"business_id": business_id})
                ids = []
            done = self._ingest(business_id, reader, ids)
            store.update(history_id=latest)
            if ids:
                self.rt.audit.append("gmail.polled", {"business_id": business_id, "new": len(ids), "processed": done})
            self._ok(business_id, conn)
            return done
        except GmailError as exc:
            self._fail(business_id, exc, failures)
            return []
        finally:
            with self._lock:
                self._busy.discard(business_id)

    def import_recent(self, business_id: str, days: int = RECENT_DAYS) -> list[str]:
        """The optional "import the last 7 days" during onboarding: same pipeline, already-seen mail skipped."""
        if self.store(business_id).get() is None:
            raise ConnectError("Connect Gmail first.")
        with self._lock:
            if business_id in self._busy:
                raise ConnectError("Already checking this inbox; try again in a moment.")
            self._busy.add(business_id)
        try:
            reader = self.reader(business_id)
            done = self._ingest(business_id, reader, reader.recent_inbox_messages(days))
            self.rt.audit.append("gmail.imported_recent", {"business_id": business_id, "days": days,
                                                           "processed": done})
            return done
        except GmailError as exc:
            self._fail(business_id, exc, self._backoff.get(business_id, (0, 0.0))[0])
            raise ConnectError("Gmail did not answer. Please try again.") from None
        finally:
            with self._lock:
                self._busy.discard(business_id)

    def _ingest(self, business_id: str, reader: GmailReader, message_ids: list[str]) -> list[str]:
        from app.services.inbox import InboxProcessor  # services.inbox imports the runtime module

        proc = InboxProcessor(self.rt, business_id)
        done = []
        for mid in message_ids:
            raw, labels = reader.raw_message(mid)
            if "INBOX" not in labels or "DRAFT" in labels:
                continue  # sent by this account, or a draft
            if len(raw) > MAX_EMAIL_BYTES:
                self.rt.audit.append("quarantine.parse_failed", {"business_id": business_id, "source": "gmail",
                                                                 "reason": "too_large"})
                continue
            record = proc.ingest_gmail(mid, raw)
            if record is not None:
                done.append(record.email_id)
        return done

    def _ok(self, business_id: str, conn: Connection) -> None:
        with self._lock:
            self._backoff.pop(business_id, None)
        if conn.state != "connected":
            self.store(business_id).update(state="connected", last_error=None)
            self.rt.audit.append("gmail.recovered", {"business_id": business_id})
            self._publish(business_id)

    def _fail(self, business_id: str, exc: GmailError, failures: int) -> None:
        store = self.store(business_id)
        before = store.get()
        if exc.reauth:
            with self._lock:
                self._tokens.pop(business_id, None)
            store.update(state="reconnect_needed", last_error=exc.code[:80])
            self.rt.audit.append("gmail.reconnect_needed", {"business_id": business_id, "reason": exc.code[:80]})
        else:
            delay = min(MAX_BACKOFF_S, self.rt.settings.gmail_poll_seconds * 2 ** failures)
            with self._lock:
                self._backoff[business_id] = (failures + 1, time.monotonic() + delay)
            store.update(state="unreachable", last_error=exc.code[:80])
            self.rt.audit.append("gmail.poll_failed", {"business_id": business_id, "reason": exc.code[:80],
                                                       "retry_in_s": int(delay)})
        after = store.get()
        if before is None or after is None or before.state != after.state:
            self._publish(business_id)

    def poll_all(self) -> None:
        if self.missing_settings():
            return
        for b in list_businesses(self.rt.data_dir):
            if (self.rt.data_dir / b.id / "gmail.sqlite").is_file():
                try:
                    self.poll(b.id)
                except Exception:  # one business's failure must not stop the others; details are in the audit log
                    log.exception("gmail poll failed for %s", b.id)

    # ---- Sending (handed to the gateway's executor) ----------------------------------------------------------------
    def mail_route(self, business_id: str) -> MailRoute:
        rt = self.rt

        def business_name() -> str:
            with rt.business(business_id) as conn:
                return business_info(conn).name

        def recipient(contact_id: str) -> Recipient | None:
            with rt.business(business_id) as conn:
                info = business_info(conn)
                directory = load_directory(conn, records_folder(conn, rt.settings.seed_dir), info.name)
            cp = directory.counterparties.get(contact_id)
            if cp is None:
                return None
            return Recipient(cp.name, sorted(cp.emails)[0] if cp.emails else None)

        def gmail() -> GmailSendAccess | None:
            store = self.store(business_id)
            conn = store.get()
            if conn is None or conn.state == "reconnect_needed" or store.source() != "gmail":
                return None
            return GmailSendAccess(conn.email_address, lambda: self.access_token(business_id), self.http)

        def flagged_senders() -> FlaggedSenders:
            path = rt.data_dir / business_id / "inbox.sqlite"
            addresses: set[str] = set()
            ids: set[str] = set()
            for r in InboxStore(path).all() if path.is_file() else []:
                if not r.sentinel.flags:
                    continue
                addresses.update(a.lower() for a in (r.from_address, r.reply_to_address) if a)
                if r.sentinel.sender_counterparty_id:
                    ids.add(r.sentinel.sender_counterparty_id)
            return FlaggedSenders(frozenset(addresses), frozenset(ids))

        def contacts() -> list[tuple[str, str, str, str]]:
            with rt.business(business_id) as conn:
                info = business_info(conn)
                directory = load_directory(conn, records_folder(conn, rt.settings.seed_dir), info.name)
            return [(cp.id, cp.name, cp.kind, sorted(cp.emails)[0]) for cp in directory.counterparties.values()
                    if cp.emails and cp.kind in ("customer", "supplier")]

        return MailRoute(business_name, recipient, gmail, rt.settings.send_allowlist, flagged_senders, contacts)


class GmailPoller:
    """Polls every connected inbox every GMAIL_POLL_SECONDS on a daemon thread (Pub/Sub push is out of scope)."""

    def __init__(self, rt, interval_s: float):
        self.rt = rt
        self.interval_s = interval_s
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="gmail-poller", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        while not self._stop.wait(self.interval_s):
            try:
                self.rt.gmail.poll_all()
            except Exception:
                log.exception("gmail poller")
