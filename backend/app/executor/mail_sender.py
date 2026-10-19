"""Outbound email for approved actions: through Gmail when it is safe to, otherwise into the sandbox outbox.

Real Gmail sending happens only when all of these hold: Gmail is connected, healthy and the active inbox; the
recipient is a known contact with an email address on file (looked up by ID in the business's own contact book,
never taken from an email); and that address is on DEMO_SEND_ALLOWLIST. Anything else is stored in the sandbox
outbox with a label saying why it was not sent for real, so a rehearsal can never email a real customer by accident.
Every send, real or simulated, is recorded in the outbox; the gateway logs the result (invariant 7).

Invariant 1: import only from app.gateway.
"""

import hashlib
from collections.abc import Callable
from datetime import date

from app.connections.gmail import GmailError, MailRoute, Recipient
from app.executor import gmail_sender
from app.executor.sandbox_mailbox import SandboxMailbox


def _domain(address: str) -> str:
    return address.rsplit("@", 1)[-1].lower()


class MailSender:
    """`lookup` resolves a recipient ID: the contact book, then recipients the owner added (gateway/emails.py)."""

    def __init__(self, mailbox: SandboxMailbox, route: MailRoute | None,
                 lookup: Callable[[str], Recipient | None] | None = None):
        self.mailbox = mailbox
        self.route = route
        self.lookup = lookup or (route.recipient if route else (lambda _id: None))

    def send(self, kind: str, recipient_id: str, subject: str, body: str, details: dict, today: date) -> dict:
        """Send or simulate one email. The full text is kept in the outbox row; the returned result (which the
        gateway audits) carries only a hash of the body."""
        route = self.route
        rcpt = self.lookup(recipient_id)
        email = (rcpt.email or "").strip().lower() if rcpt else ""
        access = route.gmail() if route else None
        record = {**details, "subject": subject, "body": body}
        if access is None:
            label = "simulated: Gmail is not the connected inbox"
        elif not email:
            label = "simulated: no email address on file for this contact"
        elif email not in route.allowlist:
            label = "simulated: recipient is not on DEMO_SEND_ALLOWLIST"
        else:
            msg = gmail_sender.build_message(access.from_address, route.business_name(), email, rcpt.name, subject,
                                             body)
            try:
                message_id = gmail_sender.send(access, msg)
            except GmailError as exc:
                label = f"simulated: Gmail send failed ({exc.code})"
            else:
                out = self.mailbox.send(kind, recipient_id, {**record, "transport": "gmail",
                                                             "gmail_message_id": message_id}, today)
                return {**_audited(out, body), "transport": "gmail", "to_domain": _domain(email)}
        out = self.mailbox.send(kind, recipient_id, {**record, "transport": "sandbox", "label": label}, today)
        return {**_audited(out, body), "transport": "sandbox", "label": label}


def _audited(out: dict, body: str) -> dict:
    """A sent email's result for the audit log: the body replaced by its SHA-256 (the text is in the outbox)."""
    return {**{k: v for k, v in out.items() if k != "body"},
            "body_sha256": hashlib.sha256(body.encode("utf-8")).hexdigest()}
