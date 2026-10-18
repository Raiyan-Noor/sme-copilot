"""Parse one raw .eml into a quarantined `RawEmail` (invariant 2).

Headers are parsed here, in code: sender address and display name, Reply-To, the receiving server's SPF/DKIM/DMARC
verdicts, attachments and their hashes. The sentinel trusts these code-parsed headers, never a model's reading of
them. Body text and attachments stay inside quarantine/: they go to the extractor (no tools) and, for display only,
to the owner's UI. Nothing in a RawEmail is ever handed to the planner.
"""

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from email.utils import getaddresses, parsedate_to_datetime

from app.quarantine.html import html_to_text

MAX_EMAIL_BYTES = 5 * 1024 * 1024
MAX_ATTACHMENTS = 10


class EmailParseError(ValueError):
    pass


@dataclass(frozen=True)
class Attachment:
    filename: str
    content_type: str
    data: bytes

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.data).hexdigest()

    @property
    def kind(self) -> str:
        """pdf | image | other: decides which extractor schema applies."""
        if self.content_type == "application/pdf" or self.filename.lower().endswith(".pdf"):
            return "pdf"
        if self.content_type in ("image/png", "image/jpeg", "image/webp"):
            return "image"
        return "other"


@dataclass(frozen=True)
class RawEmail:
    email_id: str
    sha256: str
    from_address: str
    from_display_name: str
    reply_to_address: str | None
    subject: str
    sent_at: datetime | None
    auth: dict[str, str]  # spf/dkim/dmarc -> pass|fail|none, from the receiving server's Authentication-Results
    body_text: str
    html_hidden_text: list[str] = field(default_factory=list)
    attachments: list[Attachment] = field(default_factory=list)

    @property
    def from_domain(self) -> str:
        return domain_of(self.from_address)

    @property
    def reply_to_domain(self) -> str | None:
        return domain_of(self.reply_to_address) if self.reply_to_address else None


def domain_of(address: str) -> str:
    return address.rsplit("@", 1)[-1].strip().lower().rstrip(".") if "@" in address else ""


def _first_address(value: str | None) -> tuple[str, str]:
    if not value:
        return "", ""
    pairs = getaddresses([str(value)])
    return (pairs[0][0].strip(), pairs[0][1].strip().lower()) if pairs else ("", "")


_AUTH = re.compile(r"\b(spf|dkim|dmarc)=(\w+)", re.I)


def _auth_results(msg: EmailMessage) -> dict[str, str]:
    out = {"spf": "none", "dkim": "none", "dmarc": "none"}
    header = msg.get("Authentication-Results")
    if header:
        for k, v in _AUTH.findall(str(header)):
            out[k.lower()] = v.lower()
    return out


def parse_email(email_id: str, raw: bytes) -> RawEmail:
    if len(raw) > MAX_EMAIL_BYTES:
        raise EmailParseError("email too large")
    msg = BytesParser(policy=policy.default).parsebytes(raw)
    display, address = _first_address(msg.get("From"))
    if not address:
        raise EmailParseError("no From address")
    _, reply_to = _first_address(msg.get("Reply-To"))
    try:
        sent_at = parsedate_to_datetime(str(msg["Date"])) if msg.get("Date") else None
    except (TypeError, ValueError):
        sent_at = None

    texts: list[str] = []
    hidden: list[str] = []
    attachments: list[Attachment] = []
    for part in msg.walk():
        if part.is_multipart():
            continue
        ctype = part.get_content_type()
        filename = part.get_filename()
        if filename or part.get_content_disposition() == "attachment":
            if len(attachments) < MAX_ATTACHMENTS:
                attachments.append(Attachment(filename or "attachment", ctype, part.get_payload(decode=True) or b""))
        elif ctype == "text/plain":
            texts.append(part.get_content())
        elif ctype == "text/html":
            visible, invisible = html_to_text(part.get_content())
            texts.append(visible)
            hidden += invisible
    return RawEmail(
        email_id=email_id,
        sha256=hashlib.sha256(raw).hexdigest(),
        from_address=address,
        from_display_name=display,
        reply_to_address=reply_to or None,
        subject=str(msg.get("Subject") or ""),
        sent_at=sent_at,
        auth=_auth_results(msg),
        body_text="\n".join(t.strip() for t in texts if t.strip()),
        html_hidden_text=hidden,
        attachments=attachments,
    )
