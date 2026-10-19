"""Gateway state for `send_email` (T3): write-once drafts, recipients the owner added, and the flagged-sender rule.

Invariants 1, 4 and 6. An email is a draft first. The draft is a canonical JSON document whose ID is derived from its
SHA-256, so the draft ID in the action's arguments commits to the exact subject and body: the owner's Ed25519
signature covers the args hash, which covers the draft ID, which covers every byte of the text (the same scheme as
loan drafts). Text that the planner or the overnight job wrote reaches a draft only after the Numeric Firewall
rendered it from fact placeholders (agent/email_compose.py), so no number in it is invented. A draft whose bytes no
longer hash to its ID is reported as tampered and never sent.

Who may be emailed (`check_recipient`), re-run just before execution:
- a contact in the business's own contact book with an email address on file, or a recipient the owner added
  through the explicit new-address confirmation (never an address that came out of an email);
- never the sender of an email the Inbox Sentinel flagged: that sender gets the verification call script instead.

Drafts live in `<tenant>/email_drafts/<draft_id>.json`, owner-added recipients in `<tenant>/email_recipients.json`
(memory only without a tenant).
"""

import json
import re
import threading
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Literal

from app.audit.canonical import canonical_json, sha256_hex
from app.connections.gmail import FlaggedSenders, Recipient

SCHEMA = "email_draft/v1"
ID_PREFIX = "emd_"
ID_LETTERS = 24
_NIBBLE = "abcdefghijklmnop"
DRAFT_ID = re.compile(r"^emd_[a-p]{24}$")
RECIPIENT_ID = re.compile(r"^rcp_[a-p]{12}$")
EMAIL_ADDRESS = re.compile(r"^[A-Za-z0-9._%+\-]{1,64}@[A-Za-z0-9\-]{1,63}(\.[A-Za-z0-9\-]{1,63}){1,4}$")
MAX_SUBJECT = 120
MAX_BODY = 2000

Origin = Literal["planner", "overnight", "owner"]
Lookup = Literal["ok", "unknown_draft", "draft_tampered"]


def draft_id_for(sha256: str) -> str:
    return ID_PREFIX + "".join(_NIBBLE[int(c, 16)] for c in sha256[:ID_LETTERS])


def build_draft(*, recipient_id: str, subject: str, body: str, reason: str, origin: Origin,
                facts: list[dict[str, str]], about: dict[str, str] | None = None,
                edited_from: str | None = None) -> dict[str, Any]:
    """The draft document. `facts` lists the {id, display} of every placeholder the text was rendered from."""
    doc: dict[str, Any] = {"schema": SCHEMA, "recipient_id": recipient_id, "subject": subject, "body": body,
                           "reason": reason, "origin": origin, "facts": facts}
    if about:
        doc["about"] = about
    if edited_from:
        doc["edited_from"] = edited_from
    return doc


def recipient_id_for(email: str) -> str:
    """Letters-only ID for an owner-added address, derived from the address so adding it twice is one recipient."""
    digest = sha256_hex(email.strip().lower().encode())
    return "rcp_" + "".join(_NIBBLE[int(c, 16)] for c in digest[:12])


class EmailDraftStore:
    def __init__(self, folder: Path | None):
        self.folder = folder
        self._memory: dict[str, bytes] = {}
        self._lock = threading.Lock()

    def save(self, doc: dict[str, Any]) -> tuple[str, str]:
        """Store a draft; returns (draft_id, sha256). The same text always gets the same ID."""
        data = canonical_json(doc)
        digest = sha256_hex(data)
        draft_id = draft_id_for(digest)
        with self._lock:
            if self.folder is None:
                self._memory.setdefault(draft_id, data)
            else:
                self.folder.mkdir(parents=True, exist_ok=True)
                path = self.folder / f"{draft_id}.json"
                if not path.exists():
                    path.write_bytes(data)
        return draft_id, digest

    def _bytes(self, draft_id: str) -> bytes | None:
        if not DRAFT_ID.match(draft_id or ""):
            return None
        if self.folder is None:
            return self._memory.get(draft_id)
        path = self.folder / f"{draft_id}.json"
        return path.read_bytes() if path.is_file() else None

    def load(self, draft_id: str) -> tuple[Lookup, dict[str, Any] | None, str | None]:
        """(status, document, sha256). Only an intact draft comes back with its document."""
        data = self._bytes(draft_id)
        if data is None:
            return "unknown_draft", None, None
        digest = sha256_hex(data)
        if draft_id_for(digest) != draft_id:
            return "draft_tampered", None, None
        return "ok", json.loads(data), digest


@dataclass(frozen=True)
class AddedRecipient:
    id: str
    name: str
    email: str
    added_on: str


class RecipientBook:
    """Contacts the business can email: its own contact book (read-only, passed in) plus recipients the owner added
    here. Adding needs the address typed twice and an explicit confirmation (checked by the API); the planner has no
    way to add one, and an ID it was not given by a trusted tool result is untrusted and denied for this action."""

    def __init__(self, path: Path | None, contact_book, contact_list=None):
        self.path = path
        self._contact_book = contact_book
        self._contact_list = contact_list
        self._memory: dict[str, dict[str, str]] = {}
        self._lock = threading.Lock()

    def _load(self) -> dict[str, dict[str, str]]:
        if self.path is None:
            return self._memory
        if not self.path.is_file():
            return {}
        return json.loads(self.path.read_text(encoding="utf-8"))

    def _store(self, items: dict[str, dict[str, str]]) -> None:
        if self.path is None:
            self._memory = items
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(items, sort_keys=True), encoding="utf-8")
        tmp.replace(self.path)

    def add(self, name: str, email: str, today: date) -> AddedRecipient:
        email = email.strip().lower()
        if not EMAIL_ADDRESS.match(email):
            raise ValueError("that is not a valid email address")
        rid = recipient_id_for(email)
        with self._lock:
            items = self._load()
            items.setdefault(rid, {"name": name.strip(), "email": email, "added_on": today.isoformat()})
            self._store(items)
            row = items[rid]
        return AddedRecipient(rid, row["name"], row["email"], row["added_on"])

    def added(self) -> list[AddedRecipient]:
        with self._lock:
            items = self._load()
        return [AddedRecipient(k, v["name"], v["email"], v["added_on"]) for k, v in sorted(items.items())]

    def get(self, recipient_id: str) -> Recipient | None:
        """The contact book entry, else an owner-added recipient; None if neither knows this ID."""
        if RECIPIENT_ID.match(recipient_id or ""):
            with self._lock:
                row = self._load().get(recipient_id)
            return Recipient(row["name"], row["email"]) if row else None
        return self._contact_book(recipient_id) if self._contact_book else None

    def contacts(self) -> list[tuple[str, str, str, str]]:
        """Everyone the business can email, (id, name, kind, email): its contact book, then owner-added addresses."""
        book = list(self._contact_list()) if self._contact_list else []
        return book + [(a.id, a.name, "added", a.email) for a in self.added()]

    def added_by_owner(self, recipient_id: str) -> bool:
        return bool(RECIPIENT_ID.match(recipient_id or "")) and self.get(recipient_id) is not None


def check_recipient(book: RecipientBook, recipient_id: str, flagged: FlaggedSenders) -> str | None:
    """None if this recipient may be emailed, else the rule that fired."""
    rcpt = book.get(recipient_id)
    if rcpt is None:
        return "unknown_recipient"
    email = (rcpt.email or "").strip().lower()
    if not email:
        return "recipient_has_no_email"
    if recipient_id in flagged.counterparty_ids or email in flagged.addresses:
        return "recipient_flagged_sender"
    return None


def check_draft(store: EmailDraftStore, book: RecipientBook, flagged: FlaggedSenders,
                args: dict[str, Any]) -> str | None:
    """None if `args` name an intact draft for the same recipient and that recipient may be emailed."""
    status, doc, _ = store.load(str(args.get("draft_id", "")))
    if status != "ok" or doc is None:
        return status
    if doc.get("schema") != SCHEMA or doc.get("recipient_id") != args.get("recipient_id"):
        return "draft_mismatch"
    return check_recipient(book, str(args.get("recipient_id", "")), flagged)
