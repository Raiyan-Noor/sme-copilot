"""Payments: the SandboxPay connection, payees, pay requests, and settlement into the ledger.

How a payment runs (invariant 1: the gateway decides, the executor pays):
1. A request is created by the owner (manual) or from the business's records (a bill or invoice due soon, an accepted
   invoice email, or a flagged email after the call-script check). The payee and its account come from the contact
   book, never from an email; an amount from an email is marked untrusted (invariant 3).
2. If a standing mandate covers it exactly (a T2 bill payment, every value trusted), it is proposed as
   `pay_recurring_bill` and runs. Otherwise it is proposed as `pay_invoice` (T3): the owner signs a payload whose
   args hash binds payee, amount and account. The gateway re-checks before execution that the account on file is
   still that account and that a flagged-email request has its call-script check done (`check_request`).
3. The executor sends it to SandboxPay with an idempotency key; the provider answers "processing" and later posts a
   signed webhook. Only a webhook whose HMAC verifies with this connection's secret, and whose payment matches the
   request (same provider ID, amount and idempotency key), settles it. Settlement posts one ledger row (so cash,
   forecast and buffer days move), marks the bill paid, writes a canonical receipt and logs its hash, which the
   next anchoring batch includes (invariant 9). A repeated webhook changes nothing.

Every step is in the audit log (invariant 7), without tokens, secrets or account numbers. Live status goes to the
owner's screens over the inbox event stream. Nothing here is visible to the planner.
"""

import hashlib
import hmac
import json
import re
import secrets
import threading
import time
from datetime import date, timedelta
from typing import Literal

from pydantic import BaseModel

from app.audit.canonical import canonical_hash
from app.connections.crypto import TokenCipher, TokenKeyMissing
from app.connections.http import Transport, UrllibTransport
from app.connections.sandboxpay import (
    SCOPES, Connection, ConnectionStore, PaymentRoute, ProviderClient, ProviderError, authorize_url,
)
from app.gateway import ArgValue, ProposedAction
from app.ledger.pii import PiiKind, Tokenizer
from app.services.businesses import business_info, records_folder
from app.services.payment_store import OPEN_STATUSES, OwnPayee, PaymentEvent, PaymentRequest, PaymentStore

STATE_TTL_S = 600
SUGGEST_DAYS = 14
PAY_TOOLS = ("pay_invoice", "pay_recurring_bill")
NAME = re.compile(r"^[\w][\w &'.,/+()\-]{0,59}$", re.UNICODE)
TRUSTED_ITEM_SOURCES = ("invoice", "contract", "estimate")


class PaymentsError(ValueError):
    """A request the owner made that cannot be done (shown as a 422)."""


ConnectionState = Literal["connected", "not_connected", "not_configured"]


class PaymentConnectionStatus(BaseModel):
    state: ConnectionState
    provider: str = "SandboxPay"
    simulated: bool = True
    scopes: list[str] = []
    can_do: list[str]
    cannot_do: list[str]
    per_payment_cap_minor: int | None = None
    daily_cap_minor: int | None = None
    spent_today_minor: int | None = None  # from the provider; None if it could not be reached
    currency: str
    account_name: str | None = None
    connected_on: date | None = None
    provider_reachable: bool | None = None
    missing_settings: list[str] = []


class Payee(BaseModel):
    id: str
    name: str
    kind: Literal["supplier", "payee", "added"]
    account_last4: str | None = None
    verified: bool  # from the business's own contact book (not added from this screen)
    account_changed: bool = False  # a signed payee change replaced the contact book's account
    has_account: bool


class SuggestedPayment(BaseModel):
    key: str  # what to send back to create it: item:<scheduled id> or email:<email id>
    payee_id: str
    payee_name: str
    amount_minor: int
    currency: str
    due_date: date | None = None
    reference: str
    label: str
    source_kind: Literal["bill", "invoice", "email"]
    amount_untrusted: bool
    covered_by_mandate: bool  # would run without asking (a T2 bill inside the signed limit)
    needs_verification: bool = False  # from a flagged email: call the payee on a number on file first
    verified: bool = False
    flags: list[str] = []
    call_script: list[str] = []


class PaymentView(PaymentRequest):
    events: list[PaymentEvent] = []


class PaymentsOverview(BaseModel):
    connection: PaymentConnectionStatus
    payees: list[Payee]
    suggestions: list[SuggestedPayment]
    requests: list[PaymentView]


CAN_DO = ["Send payments you approve (or that a limit you signed covers) to payees you know",
          "See the status of the payments it sent"]
CANNOT_DO = ["Pay anyone who is not in your payees", "Raise the limits you approve on the provider's screen",
             "Change a payee's bank details (that needs your signature and a call)", "Move money anywhere else"]


def _last4(number: str) -> str:
    digits = re.sub(r"\D", "", number)
    return digits[-4:]


def _mailbox_email(item_id: str) -> str | None:
    """The inbox email a forecast item came from (quarantine/feed.py names them MBX-<EMAIL ID>-<n>)."""
    if not item_id.startswith("MBX-"):
        return None
    return item_id.removeprefix("MBX-").rsplit("-", 1)[0].lower()


def _sig_ok(secret: str, body: bytes, signature: str | None) -> bool:
    expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return bool(signature) and hmac.compare_digest(expected, signature or "")


class PaymentsService:
    def __init__(self, rt, transport: Transport | None = None):
        self.rt = rt
        self.http: Transport = transport or UrllibTransport()
        self._lock = threading.RLock()
        self._pending: dict[str, tuple[str, str, float]] = {}  # state -> (business_id, PKCE verifier, issued at)

    # ---- Configuration and stores --------------------------------------------------------------------------------
    def _key(self) -> str:
        s = self.rt.settings
        return (s.sandboxpay_token_key.get_secret_value() or s.gmail_token_key.get_secret_value())

    def _cipher(self) -> TokenCipher:
        return TokenCipher(self._key())

    def missing_settings(self) -> list[str]:
        missing = [] if self.rt.settings.sandboxpay_client_secret.get_secret_value().strip() else [
            "SANDBOXPAY_CLIENT_SECRET"]
        try:
            self._cipher()
        except TokenKeyMissing:
            missing.append("SANDBOXPAY_TOKEN_KEY")
        return missing

    def connection_store(self, business_id: str) -> ConnectionStore:
        return ConnectionStore(self.rt.data_dir / business_id / "sandboxpay.sqlite")

    def store(self, business_id: str) -> PaymentStore:
        return PaymentStore(self.rt.data_dir / business_id / "payments.sqlite")

    def client(self) -> ProviderClient:
        return ProviderClient(self.rt.settings.sandboxpay_url, self.http)

    def route(self, business_id: str) -> PaymentRoute:
        """What the gateway's payment executor uses for this business (see connections/sandboxpay.py)."""
        return PaymentRoute(self.connection_store(business_id), self._cipher, self.rt.settings.sandboxpay_url,
                            self.http, lambda: self.accounts(business_id),
                            lambda args: self.check_request(business_id, args))

    def attach(self, business_id: str, gateway) -> None:
        """Called once per business gateway: settlement bookkeeping follows each executed payment."""
        gateway.listeners.append(lambda tool, args, result, mandate_id:
                                 self.on_executed(business_id, tool, args, result, mandate_id))

    def _token(self, business_id: str) -> str | None:
        c = self.connection_store(business_id).get()
        if c is None:
            return None
        try:
            return self._cipher().decrypt(c.token_enc)
        except TokenKeyMissing:
            return None

    # ---- Payees: the contact book's suppliers and payees, plus any the owner added here --------------------------
    def _contacts(self, business_id: str) -> tuple[dict[str, tuple[str, str, str | None, str]], str]:
        """payee_id -> (name, kind, account number or None, last4); and the currency."""
        with self.rt.business(business_id) as conn:
            info = business_info(conn)
            folder = records_folder(conn, self.rt.settings.seed_dir)
        doc = {}
        if folder and (folder / "counterparties.json").is_file():
            doc = json.loads((folder / "counterparties.json").read_text(encoding="utf-8"))
        out: dict[str, tuple[str, str, str | None, str]] = {}
        for s in doc.get("suppliers", []):
            number = next((a.get("account_number") for a in s.get("bank_accounts", []) if a.get("account_number")),
                          None)
            out[s["id"]] = (s["name"], "supplier", number, _last4(number) if number else "")
        for p in doc.get("payees", []):
            number = p.get("account_number")
            out[p["id"]] = (p["name"], "payee", number, _last4(number) if number else "")
        return out, info.currency

    def accounts(self, business_id: str) -> dict[str, tuple[str, str]]:
        """payee_id -> (name, account token) for everyone the business can pay. Tokens use the tenant's PII key."""
        contacts, _ = self._contacts(business_id)
        out: dict[str, tuple[str, str]] = {}
        with self.rt.business(business_id) as conn:
            tok = Tokenizer(conn)
            for pid, (name, _kind, number, _l4) in contacts.items():
                if number:
                    out[pid] = (name, tok.token(PiiKind.ACCOUNT, number))
            conn.commit()
        for p in self.store(business_id).payees():
            out[p.id] = (p.name, p.account_token)
        return out

    def payees(self, business_id: str) -> list[Payee]:
        contacts, _ = self._contacts(business_id)
        accounts = self.accounts(business_id)
        gw = self.rt.gateway(business_id)
        out = []
        for pid, (name, kind, number, last4) in contacts.items():
            current = gw.payee_account(pid)
            out.append(Payee(id=pid, name=name, kind=kind, account_last4=last4 or None, verified=True,
                             has_account=current is not None,
                             account_changed=current is not None and pid in accounts and current != accounts[pid][1]))
        for p in self.store(business_id).payees():
            out.append(Payee(id=p.id, name=p.name, kind="added", account_last4=p.account_last4, verified=False,
                             has_account=True))
        return out

    def add_payee(self, business_id: str, name: str, account_number: str, confirm_account_number: str,
                  confirmed: bool) -> Payee:
        """A new payee needs the owner's extra confirmation: the account number typed twice, and an explicit tick.
        It is tokenized at once; only its last four digits are kept for display."""
        name = name.strip()
        if not NAME.match(name):
            raise PaymentsError("Use a short name: letters, digits, spaces and . , & ' - ( ) / +")
        digits, again = re.sub(r"\D", "", account_number), re.sub(r"\D", "", confirm_account_number)
        if not (6 <= len(digits) <= 34):
            raise PaymentsError("The account number should have 6 to 34 digits.")
        if digits != again:
            raise PaymentsError("The two account numbers do not match.")
        if not confirmed:
            raise PaymentsError("Confirm that you checked this account with the payee yourself.")
        with self.rt.business(business_id) as conn:
            token = Tokenizer(conn).token(PiiKind.ACCOUNT, digits)
            conn.commit()
        if token in {t for _n, t in self.accounts(business_id).values()}:
            raise PaymentsError("This account already belongs to one of your payees.")
        payee = OwnPayee(id="pay_own_" + secrets.token_hex(4), name=name, account_token=token,
                         account_last4=digits[-4:], added_on=self.rt.clock.today())
        self.store(business_id).add_payee(payee)
        self.rt.audit.append("payments.payee_added", {"business_id": business_id, "payee_id": payee.id,
                                                      "account_token": token, "confirmed_twice": True})
        return Payee(id=payee.id, name=name, kind="added", account_last4=payee.account_last4, verified=False,
                     has_account=True)

    # ---- Connection --------------------------------------------------------------------------------------------
    def status(self, business_id: str, *, live: bool = True) -> PaymentConnectionStatus:
        with self.rt.business(business_id) as conn:
            currency = business_info(conn).currency
        missing = self.missing_settings()
        c = self.connection_store(business_id).get()
        base = {"can_do": CAN_DO, "cannot_do": CANNOT_DO, "currency": currency}
        if c is None:
            return PaymentConnectionStatus(state="not_configured" if missing else "not_connected",
                                           missing_settings=missing, **base)
        spent, reachable = None, None
        token = self._token(business_id)
        if live and token:
            try:
                spent, reachable = int(self.client().connection(token).get("spent_today_minor", 0)), True
            except ProviderError:
                reachable = False
        return PaymentConnectionStatus(
            state="connected", scopes=list(c.scopes), per_payment_cap_minor=c.per_payment_cap_minor,
            daily_cap_minor=c.daily_cap_minor, spent_today_minor=spent, account_name=c.account_name,
            connected_on=c.connected_on, provider_reachable=reachable, **{**base, "currency": c.currency})

    def start(self, business_id: str, client_name: str) -> str:
        """The provider's consent URL for this business: a one-time state bound to a fresh PKCE verifier."""
        from app.connections.gmail import pkce_pair

        with self.rt.business(business_id) as conn:
            info = business_info(conn)
        missing = self.missing_settings()
        if missing:
            raise PaymentsError(f"The payment service is not set up on this server: set {', '.join(missing)} in .env.")
        s = self.rt.settings
        state = secrets.token_urlsafe(32)
        verifier, challenge = pkce_pair()
        now = time.monotonic()
        with self._lock:
            self._pending = {k: v for k, v in self._pending.items() if now - v[2] < STATE_TTL_S}
            self._pending[state] = (business_id, verifier, now)
        self.rt.audit.append("payments.connect_started", {
            "business_id": business_id, "scopes": list(SCOPES), "per_payment_cap_minor": s.sandboxpay_per_payment_cap_minor,
            "daily_cap_minor": s.sandboxpay_daily_cap_minor})
        return authorize_url(s.sandboxpay_public_url or s.sandboxpay_url, s.sandboxpay_client_id,
                             s.sandboxpay_redirect_uri, state, challenge,
                             per_payment_cap=s.sandboxpay_per_payment_cap_minor,
                             daily_cap=s.sandboxpay_daily_cap_minor, currency=info.currency,
                             client_name=client_name[:60] or "Your finance assistant", account_name=info.name)

    def finish(self, state: str | None, code: str | None, error: str | None) -> str:
        """Complete the consent callback; returns the business ID. Raises PaymentsError."""
        with self._lock:
            entry = self._pending.pop(state, None) if state else None
        if entry is None or time.monotonic() - entry[2] > STATE_TTL_S:
            self.rt.audit.append("payments.connect_failed", {"business_id": entry[0] if entry else None,
                                                             "reason": "bad_state"})
            raise PaymentsError("This connection was not started here, or it has expired. Start again from the app.")
        business_id, verifier, _ = entry

        def fail(reason: str, message: str) -> PaymentsError:
            self.rt.audit.append("payments.connect_failed", {"business_id": business_id, "reason": reason[:60]})
            return PaymentsError(message)

        if error or not code:
            raise fail(error or "no_code", "The connection was cancelled on the payment service. Nothing changed.")
        s = self.rt.settings
        webhook = f"{s.sandboxpay_webhook_base.rstrip('/')}/{business_id}"
        try:
            grant = self.client().exchange(s.sandboxpay_client_id, s.sandboxpay_client_secret.get_secret_value(),
                                           code, verifier, s.sandboxpay_redirect_uri, webhook)
        except ProviderError as exc:
            raise fail(f"exchange:{exc.code}", "The payment service did not accept the connection.") from None
        scopes = tuple(str(grant.get("scope", "")).split())
        if "payments.send" not in scopes:
            self.client().revoke(str(grant.get("access_token", "")))
            raise fail("scopes", "Sending payments was not allowed, so nothing was connected.")
        store = self.connection_store(business_id)
        previous = self._token(business_id)
        cipher = self._cipher()
        store.save(Connection(str(grant["connection_id"]), cipher.encrypt(str(grant["access_token"])),
                              cipher.encrypt(str(grant["webhook_secret"])), scopes,
                              int(grant["per_payment_cap_minor"]), int(grant["daily_cap_minor"]),
                              str(grant["currency"]), str(grant.get("account_name") or ""), self.rt.clock.today()))
        if previous:  # reconnecting: retire the old token
            try:
                self.client().revoke(previous)
            except ProviderError:
                pass
        self.rt.audit.append("payments.provider_connected", {
            "business_id": business_id, "provider": "sandboxpay", "connection_id": grant["connection_id"],
            "scopes": list(scopes), "per_payment_cap_minor": grant["per_payment_cap_minor"],
            "daily_cap_minor": grant["daily_cap_minor"], "reconnect": previous is not None})
        self._publish_connection(business_id)
        return business_id

    def disconnect(self, business_id: str) -> PaymentConnectionStatus:
        """Revoke the token at the provider first (it stops working there immediately), then delete it here."""
        store = self.connection_store(business_id)
        c = store.get()
        revoked = False
        if c is not None:
            token = self._token(business_id)
            if token:
                try:
                    revoked = self.client().revoke(token)
                except ProviderError:
                    revoked = False
            store.delete()
            self.rt.audit.append("payments.provider_disconnected", {
                "business_id": business_id, "connection_id": c.connection_id, "revoked": revoked})
            self._publish_connection(business_id)
        return self.status(business_id, live=False)

    def _publish_connection(self, business_id: str) -> None:
        self.rt.inbox_events.publish(business_id, kind="payment_connection",
                                     connection=self.status(business_id, live=False).model_dump(mode="json"))

    def _publish(self, business_id: str, r: PaymentRequest) -> None:
        self.rt.inbox_events.publish(business_id, kind="payment", payment={
            "request_id": r.id, "status": r.status, "payee_name": r.payee_name, "amount_minor": r.amount_minor,
            "currency": r.currency, "rule": r.rule})

    # ---- Suggestions from the business's records --------------------------------------------------------------
    def suggestions(self, business_id: str) -> list[SuggestedPayment]:
        from app.services.inbox import load_inbox

        today = self.rt.clock.today()
        accounts = self.accounts(business_id)
        store = self.store(business_id)
        taken_items = {r.scheduled_item_id for r in store.all() if r.status in OPEN_STATUSES and r.scheduled_item_id}
        taken_emails = {r.email_id for r in store.all() if r.status in OPEN_STATUSES and r.email_id}
        with self.rt.business(business_id) as conn:
            currency = business_info(conn).currency
            items = conn.execute(
                "SELECT * FROM scheduled_items WHERE kind = 'payable' AND status = 'open' AND due_date <= ?"
                " ORDER BY due_date, id", ((today + timedelta(days=SUGGEST_DAYS)).isoformat(),)).fetchall()
        gw = self.rt.gateway(business_id)
        out: list[SuggestedPayment] = []
        for it in items:
            pid = it["counterparty_id"]
            if pid not in accounts or it["id"] in taken_items:
                continue
            from_mail = (it["source"] or "").startswith("mailbox")
            if not from_mail and it["source"] not in TRUSTED_ITEM_SOURCES:
                continue
            ref = it["reference"] or it["id"]
            kind = "invoice" if from_mail or it["source"] == "invoice" else "bill"
            label = (f"From invoice {ref} (arrived by email)" if from_mail else
                     f"Invoice {ref}" if kind == "invoice" else f"Bill {ref}")
            covered = not from_mail and gw.mandate_covers(self._bill_action(pid, it["id"], it["amount_minor"]))
            out.append(SuggestedPayment(
                key=f"item:{it['id']}", payee_id=pid, payee_name=accounts[pid][0], amount_minor=it["amount_minor"],
                currency=currency, due_date=date.fromisoformat(it["due_date"]), reference=ref, label=label,
                source_kind=kind, amount_untrusted=from_mail, covered_by_mandate=covered))
        for rec in reversed(load_inbox(self.rt, business_id)):  # newest first
            rep = rec.sentinel
            pid = rep.payee_counterparty_id
            if not rep.flags or not rep.payment_requested or pid not in accounts or rec.email_id in taken_emails:
                continue
            amount = rec.fields.amount_minor.value if rec.fields.amount_minor else None
            if not amount:
                continue
            ref = rec.fields.invoice_number.value if rec.fields.invoice_number else rec.email_id
            needs = rep.call_script is not None or rep.hold
            out.append(SuggestedPayment(
                key=f"email:{rec.email_id}", payee_id=pid, payee_name=accounts[pid][0], amount_minor=amount,
                currency=currency, due_date=rec.fields.due_date.value if rec.fields.due_date else None,
                reference=ref, label=f"Flagged email from {rec.from_display_name or rec.from_address}",
                source_kind="email", amount_untrusted=True, covered_by_mandate=False, needs_verification=needs,
                verified=store.verified(rec.email_id), flags=[f.code for f in rep.flags],
                call_script=rep.call_script.lines if rep.call_script else []))
        return out

    def verify_call(self, business_id: str, email_id: str) -> None:
        """The owner marks the call-script check done for a flagged email (they called a number from their own
        records and the payee confirmed). Payments sourced from that email are blocked by the gateway until then."""
        from app.services.inbox import store_for

        rec = store_for(self.rt, business_id).get(email_id)
        if rec is None or not rec.sentinel.flags:
            raise PaymentsError("Only a flagged email needs a verification call.")
        self.store(business_id).verify(email_id, self.rt.clock.today())
        self.rt.audit.append("payments.call_verified", {"business_id": business_id, "email_id": email_id,
                                                        "flags": [f.code for f in rec.sentinel.flags]})

    # ---- Requests --------------------------------------------------------------------------------------------
    @staticmethod
    def _bill_action(payee_id: str, bill_id: str, amount: int) -> ProposedAction:
        t = lambda v: ArgValue(value=v, provenance="trusted")  # noqa: E731
        return ProposedAction(tool="pay_recurring_bill", args={"payee_id": t(payee_id), "bill_id": t(bill_id),
                                                               "amount_minor": t(amount)})

    def create(self, business_id: str, *, source: str | None, payee_id: str | None, amount_minor: int | None,
               reason: str, reference: str | None) -> PaymentView:
        """Create a pay request and put it to the gateway at once. For a suggestion (`source` = its key) payee and
        amount come from the business's records; for a manual request, from the owner."""
        today = self.rt.clock.today()
        accounts = self.accounts(business_id)
        store = self.store(business_id)
        rid = "pr_" + secrets.token_hex(8)
        reason = " ".join(reason.split())[:200]
        if source:
            found = next((s for s in self.suggestions(business_id) if s.key == source), None)
            if found is None:
                raise PaymentsError("That payment is no longer suggested (already requested, paid or not due).")
            if found.needs_verification and not found.verified:
                raise PaymentsError("Make the verification call first: this email was flagged.")
            kind, sref = source.split(":", 1)
            req = PaymentRequest(
                id=rid, created_on=today, payee_id=found.payee_id, payee_name=found.payee_name,
                amount_minor=found.amount_minor, currency=found.currency, reference=found.reference[:64],
                reason=reason or found.label, source_kind=found.source_kind, source_ref=sref,
                source_label=found.label, amount_untrusted=found.amount_untrusted,
                scheduled_item_id=sref if kind == "item" else None,
                email_id=sref if kind == "email" else _mailbox_email(sref),
                status="proposed")
        else:
            if payee_id not in accounts:
                raise PaymentsError("Pick one of your payees (add a new one first if needed).")
            if not isinstance(amount_minor, int) or amount_minor <= 0:
                raise PaymentsError("Enter an amount above zero.")
            with self.rt.business(business_id) as conn:
                currency = business_info(conn).currency
            req = PaymentRequest(
                id=rid, created_on=today, payee_id=payee_id, payee_name=accounts[payee_id][0],
                amount_minor=amount_minor, currency=currency, reference=(reference or rid).strip()[:64] or rid,
                reason=reason or "Payment you entered", source_kind="manual", source_label="Entered by you",
                amount_untrusted=False, status="proposed")
        if not req.reference.strip():
            req = req.model_copy(update={"reference": rid})
        store.add(req)
        store.add_event(rid, today, "proposed")
        self.rt.audit.append("payments.request_created", {
            "business_id": business_id, "request_id": rid, "payee_id": req.payee_id, "amount_minor": req.amount_minor,
            "source_kind": req.source_kind, "source_ref": req.source_ref, "amount_untrusted": req.amount_untrusted})
        return self.submit(business_id, rid)

    def submit(self, business_id: str, request_id: str) -> PaymentView:
        """Put a proposed request to the gateway: a T2 bill inside a signed limit runs; everything else waits for the
        owner's signature on payee + amount + account."""
        store = self.store(business_id)
        req = store.get(request_id)
        if req is None or req.status != "proposed":
            raise PaymentsError("Only a proposed payment can be submitted.")
        gw = self.rt.gateway(business_id)
        today = self.rt.clock.today()
        bill_id = req.scheduled_item_id or req.id
        bill = self._bill_action(req.payee_id, bill_id, req.amount_minor)
        if not req.amount_untrusted and req.source_kind in ("bill", "invoice", "manual") and gw.mandate_covers(bill):
            store.update(request_id, tool="pay_recurring_bill", bill_id=bill_id)
            decision = gw.propose(bill)
        else:
            account = gw.payee_account(req.payee_id)
            if account is None:
                raise PaymentsError("This payee has no account on file.")
            provenance = lambda name: "untrusted" if name == "amount_minor" and req.amount_untrusted else "trusted"  # noqa: E731
            values = {"payee_id": req.payee_id, "account_token": account, "amount_minor": req.amount_minor,
                      "reference": req.reference, "request_id": req.id}
            store.update(request_id, tool="pay_invoice", account_token=account,
                         account_last4=self._last4_for(business_id, account))
            decision = gw.propose(ProposedAction(tool="pay_invoice", args={
                k: ArgValue(value=v, provenance=provenance(k)) for k, v in values.items()}))
        if decision.status == "pending_approval":
            store.update(request_id, status="awaiting_approval", approval_id=decision.approval.approval_id)
            store.add_event(request_id, today, "awaiting_approval", decision.rule)
        elif decision.status == "denied":
            store.update(request_id, status="denied", rule=decision.rule)
            store.add_event(request_id, today, "denied", decision.rule)
        # executed: the listener has already recorded approved -> sent (or failed)
        self.rt.audit.append("payments.request_submitted", {
            "business_id": business_id, "request_id": request_id, "tool": store.get(request_id).tool,
            "gateway_status": decision.status, "rule": decision.rule})
        out = self.view(business_id, request_id)
        self._publish(business_id, out)
        return out

    def _last4_for(self, business_id: str, account: str) -> str | None:
        """Last four digits of an account token, for display (the vault holds the number; only these leave)."""
        with self.rt.business(business_id) as conn:
            row = conn.execute("SELECT value FROM pii_vault WHERE token = ?", (account,)).fetchone()
        return str(row["value"])[-4:] if row else None

    def cancel(self, business_id: str, request_id: str) -> PaymentView:
        store = self.store(business_id)
        req = store.get(request_id)
        if req is None or req.status not in ("proposed", "awaiting_approval"):
            raise PaymentsError("Only a payment that has not been sent can be cancelled.")
        if req.approval_id:
            gw = self.rt.gateway(business_id)
            approval = gw.store.get_approval(req.approval_id)
            if approval is not None and approval.status == "pending":
                gw.store.set_approval_status(req.approval_id, "cancelled")
        store.update(request_id, status="cancelled")
        store.add_event(request_id, self.rt.clock.today(), "cancelled")
        self.rt.audit.append("payments.request_cancelled", {"business_id": business_id, "request_id": request_id,
                                                            "approval_id": req.approval_id})
        out = self.view(business_id, request_id)
        self._publish(business_id, out)
        return out

    def check_request(self, business_id: str, args: dict) -> str | None:
        """The gateway's precheck for `pay_invoice`, at proposal and again just before execution: the request exists,
        is still open, matches the signed args exactly, and a flagged-email request has its call-script check done."""
        req = self.store(business_id).get(str(args.get("request_id")))
        if req is None:
            return "unknown_payment_request"
        if req.status not in ("proposed", "awaiting_approval"):
            return f"payment_request_{req.status}"
        if (req.payee_id, req.amount_minor, req.reference) != (args["payee_id"], args["amount_minor"],
                                                               args["reference"]):
            return "payment_request_mismatch"
        if req.source_kind == "email" and req.email_id:
            from app.services.inbox import store_for

            rec = store_for(self.rt, business_id).get(req.email_id)
            flagged = rec is not None and (rec.sentinel.call_script is not None or rec.sentinel.hold)
            if flagged and not self.store(business_id).verified(req.email_id):
                return "call_script_verification_required"
        return None

    # ---- Execution, webhooks and settlement ------------------------------------------------------------------
    def on_executed(self, business_id: str, tool: str, args: dict, result: dict, mandate_id: int) -> None:
        if tool not in PAY_TOOLS:
            return
        store = self.store(business_id)
        today = self.rt.clock.today()
        if tool == "pay_invoice":
            req = store.get(args["request_id"])
        else:
            req = store.by_bill(args["bill_id"], ("proposed", "awaiting_approval"))
        if req is None:  # a bill paid by the assistant under a mandate: keep a record of it too
            accounts = self.accounts(business_id)
            with self.rt.business(business_id) as conn:
                currency = business_info(conn).currency
            req = PaymentRequest(
                id="pr_" + secrets.token_hex(8), created_on=today, payee_id=args["payee_id"],
                payee_name=accounts.get(args["payee_id"], (args["payee_id"], ""))[0],
                amount_minor=args["amount_minor"], currency=currency, reference=str(args["bill_id"])[:64],
                reason="Paid by the assistant under your signed limit", source_kind="assistant",
                source_label="Assistant, within your limit", amount_untrusted=False, tool=tool,
                bill_id=args["bill_id"], status="proposed")
            store.add(req)
            store.add_event(req.id, today, "proposed")
        if result.get("provider_status") == "duplicate":
            store.add_event(req.id, today, req.status, "duplicate send refused by idempotency key")
            return
        store.add_event(req.id, today, "approved", "signed by you" if tool == "pay_invoice" else "within your limit")
        fields = {"mandate_id": mandate_id, "idempotency_key": result.get("idempotency_key"),
                  "provider_payment_id": result.get("provider_payment_id")}
        if result.get("provider_payment_id"):
            store.update(req.id, status="sent", **fields)
            store.add_event(req.id, today, "sent", "SandboxPay: processing")
            self.rt.audit.append("payments.sent", {"business_id": business_id, "request_id": req.id,
                                                   "provider_payment_id": result["provider_payment_id"],
                                                   "idempotency_key": result.get("idempotency_key")})
        else:
            reason = str(result.get("reason") or result.get("provider_status") or "not_sent")
            store.update(req.id, status="failed", rule=reason, **fields)
            store.add_event(req.id, today, "failed", reason)
            self.rt.audit.append("payments.failed", {"business_id": business_id, "request_id": req.id,
                                                     "reason": reason, "stage": "send"})
        self._publish(business_id, store.get(req.id))

    def webhook(self, business_id: str, body: bytes, signature: str | None) -> tuple[bool, str]:
        """A provider webhook. Returns (accepted, outcome). Nothing changes unless the signature verifies."""
        c = self.connection_store(business_id).get()
        secret = None
        if c is not None:
            try:
                secret = self._cipher().decrypt(c.webhook_secret_enc)
            except TokenKeyMissing:
                secret = None
        if secret is None or not _sig_ok(secret, body, signature):
            self.rt.audit.append("payments.webhook_rejected", {"business_id": business_id, "reason": "bad_signature",
                                                               "body_sha256": hashlib.sha256(body).hexdigest()})
            return False, "bad_signature"
        try:
            event = json.loads(body)
            kind, payment = str(event["type"]), dict(event["payment"])
        except (ValueError, KeyError, TypeError):
            self.rt.audit.append("payments.webhook_rejected", {"business_id": business_id, "reason": "malformed"})
            return False, "malformed"
        self.rt.audit.append("payments.webhook_received", {
            "business_id": business_id, "type": kind[:40], "provider_payment_id": str(payment.get("id"))[:40],
            "body_sha256": hashlib.sha256(body).hexdigest()})
        return True, self._apply(business_id, payment, kind.removeprefix("payment."))

    def refresh(self, business_id: str, request_id: str) -> PaymentView:
        """Ask the provider for a sent payment's status (if a webhook went missing)."""
        req = self.store(business_id).get(request_id)
        token = self._token(business_id)
        if req is None:
            raise PaymentsError("No such payment.")
        if req.status == "sent" and req.provider_payment_id and token:
            try:
                res = self.http.request("GET", f"{self.rt.settings.sandboxpay_url.rstrip('/')}/v1/payments/"
                                               f"{req.provider_payment_id}",
                                        headers={"Authorization": f"Bearer {token}"})
            except Exception:  # noqa: BLE001 - unreachable: keep waiting for the webhook
                res = None
            if res is not None and res.ok and isinstance(res.body, dict):
                self.rt.audit.append("payments.status_checked", {"business_id": business_id, "request_id": request_id,
                                                                 "provider_status": str(res.body.get("status"))[:20]})
                if res.body.get("status") in ("settled", "failed"):
                    self._apply(business_id, res.body, str(res.body["status"]))
        return self.view(business_id, request_id)

    def _apply(self, business_id: str, payment: dict, outcome: str) -> str:
        store = self.store(business_id)
        req = store.by_provider_payment(str(payment.get("id")))
        if req is None:
            self.rt.audit.append("payments.webhook_unmatched", {"business_id": business_id,
                                                                "provider_payment_id": str(payment.get("id"))[:40]})
            return "unknown_payment"
        if req.status in ("settled", "failed"):
            self.rt.audit.append("payments.webhook_duplicate", {"business_id": business_id, "request_id": req.id,
                                                                "status": req.status})
            return "duplicate"
        if payment.get("amount_minor") != req.amount_minor or payment.get("idempotency_key") != req.idempotency_key:
            self.rt.audit.append("payments.webhook_mismatch", {"business_id": business_id, "request_id": req.id})
            return "mismatch"
        if outcome == "settled":
            self._settle(business_id, req)
            return "settled"
        if outcome == "failed":
            reason = str(payment.get("failure_reason") or "failed")[:40]
            store.update(req.id, status="failed", rule=reason)
            store.add_event(req.id, self.rt.clock.today(), "failed", f"SandboxPay: {reason}")
            self.rt.audit.append("payments.failed", {"business_id": business_id, "request_id": req.id,
                                                     "reason": reason, "stage": "settlement"})
            self._publish(business_id, store.get(req.id))
            return "failed"
        return "ignored"

    def _settle(self, business_id: str, req: PaymentRequest) -> None:
        """Post the payment to the ledger, close the bill, write the receipt and log its hash for anchoring."""
        today = self.rt.clock.today()
        store = self.store(business_id)
        gw = self.rt.gateway(business_id)
        account = req.account_token or gw.payee_account(req.payee_id)
        tx_id, import_id = f"txn_{req.id}", f"pay_{req.id}"
        mandate = gw.store.mandate_document(req.mandate_id) if req.mandate_id else None
        receipt = {
            "schema": "payment_receipt/v1", "business_id": business_id, "request_id": req.id,
            "provider": "sandboxpay", "provider_payment_id": req.provider_payment_id,
            "idempotency_key": req.idempotency_key, "payee_id": req.payee_id, "account_token": account,
            "amount_minor": req.amount_minor, "currency": req.currency, "reference": req.reference,
            "settled_on": today.isoformat(), "tool": req.tool, "approval_id": req.approval_id,
            "mandate_id": req.mandate_id, "mandate_record_hash": mandate[1] if mandate else None,
            "ledger_tx_id": tx_id,
        }
        receipt_sha256 = canonical_hash(receipt)
        with self.rt.business(business_id) as conn:
            category = None
            if req.scheduled_item_id:
                row = conn.execute("SELECT category FROM scheduled_items WHERE id = ?",
                                   (req.scheduled_item_id,)).fetchone()
                category = row["category"] if row else None
            with conn:
                conn.execute("INSERT OR IGNORE INTO accounts (id, name, currency) VALUES (?, ?, ?)",
                             ("sandboxpay", "SandboxPay payments", req.currency))
                conn.execute(
                    "INSERT OR IGNORE INTO imports (id, account_id, source_name, file_sha256, row_count, inserted,"
                    " duplicates) VALUES (?, 'sandboxpay', 'SandboxPay payment', ?, 1, 1, 0)", (import_id,
                                                                                               receipt_sha256))
                conn.execute(
                    "INSERT OR IGNORE INTO transactions (id, account_id, posted_on, amount_minor, currency,"
                    " description, counterparty, counterparty_ref, reference, channel, category, balance_minor,"
                    " import_id, source_line) VALUES (?, 'sandboxpay', ?, ?, ?, ?, ?, ?, ?, 'sandboxpay', ?, NULL, ?, 1)",
                    (tx_id, today.isoformat(), -req.amount_minor, req.currency, f"Payment to {req.payee_name}",
                     req.payee_name, account, req.reference, category, import_id))
                if req.scheduled_item_id:
                    conn.execute("UPDATE scheduled_items SET status = 'paid' WHERE id = ?", (req.scheduled_item_id,))
        store.update(req.id, status="settled", ledger_tx_id=tx_id, receipt=json.dumps(receipt, sort_keys=True),
                     receipt_sha256=receipt_sha256, settled_on=today)
        store.add_event(req.id, today, "settled", "SandboxPay: settled")
        self.rt.audit.append("payments.settled", {
            "business_id": business_id, "request_id": req.id, "provider_payment_id": req.provider_payment_id,
            "amount_minor": req.amount_minor, "ledger_tx_id": tx_id, "scheduled_item_id": req.scheduled_item_id,
            "mandate_id": req.mandate_id, "receipt_sha256": receipt_sha256})
        self.rt.anchors.request("payment_settled")  # the receipt hash joins the next batch (invariant 9)
        self._publish(business_id, store.get(req.id))

    # ---- Views ---------------------------------------------------------------------------------------------
    def view(self, business_id: str, request_id: str) -> PaymentView:
        store = self.store(business_id)
        req = store.get(request_id)
        if req is None:
            raise PaymentsError("No such payment.")
        return PaymentView(**req.model_dump(), events=store.events(request_id))

    def receipt(self, business_id: str, request_id: str) -> tuple[dict, str] | None:
        """The stored receipt document and the hash recorded at settlement."""
        store = self.store(business_id)
        req = store.get(request_id)
        doc = store.receipt(request_id)
        return (doc, req.receipt_sha256) if req and doc and req.receipt_sha256 else None

    def overview(self, business_id: str, status: str | None = None, payee_id: str | None = None,
                 live: bool = True) -> PaymentsOverview:
        store = self.store(business_id)
        requests = [r for r in store.all() if (status is None or r.status == status)
                    and (payee_id is None or r.payee_id == payee_id)]
        return PaymentsOverview(
            connection=self.status(business_id, live=live), payees=self.payees(business_id),
            suggestions=self.suggestions(business_id),
            requests=[PaymentView(**r.model_dump(), events=store.events(r.id)) for r in requests])
