"""Inbox processing: mailbox/upload -> quarantine (parse, extract) -> typed fields -> sentinel -> store -> forecast.

Invariant 2: raw email content flows only from the .eml file into quarantine/ (the extractor and the owner's detail
view). What leaves is `InboxRecord`: code-parsed headers, typed provenance-tagged fields and the sentinel report.
Invariant 7: every step is in the audit log (hashes, statuses, flags; never message text).

The mailbox for a business is listed in the seed manifest (`mailbox.business_id`); only each email's ID and file
are read from it, never its expected results. Emails dated after the simulated today are not delivered yet.
"""

import json
import re
import secrets
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from app.ledger.pii import Tokenizer
from app.quarantine.extractor import Extraction, Extractor, email_message, invoice_message, receipt_message
from app.quarantine.feed import existing_items, plan_items, write_items
from app.quarantine.mime import RawEmail, parse_email
from app.quarantine.pdf import extract_pdf_text
from app.quarantine.signals import scan
from app.quarantine.store import AttachmentInfo, InboxRecord, InboxStore
from app.quarantine.typed import build_fields
from app.sentinel.checks import Headers, LedgerInvoice, TextEvidence, assess
from app.sentinel.directory import Directory, load_directory
from app.services.businesses import business_info
from app.services.runtime import Runtime

EMAIL_ID = re.compile(r"^(em|up)-[a-z0-9]{3,16}$")


@dataclass(frozen=True)
class SyncReport:
    processed: list[str]
    skipped_existing: int
    not_yet_delivered: int
    failed: list[str]


def store_for(rt: Runtime, business_id: str) -> InboxStore:
    return InboxStore(rt.data_dir / business_id / "inbox.sqlite")


def upload_dir(rt: Runtime, business_id: str) -> Path:
    return rt.data_dir / business_id / "inbox_uploads"


def mailbox_files(rt: Runtime, seed_source: str | None) -> list[tuple[str, Path]]:
    manifest = rt.settings.seed_dir / "manifest.json"
    if not seed_source or not manifest.is_file():
        return []
    box = json.loads(manifest.read_text(encoding="utf-8")).get("mailbox") or {}
    if box.get("business_id") != seed_source:
        return []
    out = []
    for e in box.get("emails", []):
        eid, path = str(e.get("id", "")), rt.settings.seed_dir / str(e.get("file", ""))
        if EMAIL_ID.match(eid) and path.is_file() and path.resolve().is_relative_to(rt.settings.seed_dir.resolve()):
            out.append((eid, path))
    return out


def raw_path(rt: Runtime, business_id: str, email_id: str) -> Path | None:
    """Where the owner's detail view reads the raw message from."""
    if email_id.startswith("up-"):
        p = upload_dir(rt, business_id) / f"{email_id}.eml"
        return p if p.is_file() else None
    with rt.business(business_id) as conn:
        source = business_info(conn).seed_source
    return dict(mailbox_files(rt, source)).get(email_id)


def _ledger_invoices(conn: sqlite3.Connection) -> dict[str, LedgerInvoice]:
    out = {}
    for s in existing_items(conn):
        if s.reference and not (s.source or "").startswith("mailbox"):
            out[s.reference] = LedgerInvoice(s.reference, s.amount_minor, s.due_date, s.counterparty_id)
    return out


class InboxProcessor:
    def __init__(self, rt: Runtime, business_id: str, llm=None):
        self.rt = rt
        self.business_id = business_id
        self.extractor = Extractor(llm if llm is not None else rt.llm, rt.audit)
        self.store = store_for(rt, business_id)

    def _directory(self, conn: sqlite3.Connection) -> tuple[Directory, str]:
        info = business_info(conn)
        folder = self.rt.settings.seed_dir / info.seed_source if info.seed_source else None
        return load_directory(conn, folder, info.name), info.currency

    def sync(self) -> SyncReport:
        with self.rt.business(self.business_id) as conn:
            source = business_info(conn).seed_source
        today = self.rt.clock.today()
        pending: list[RawEmail] = []
        skipped = later = 0
        failed: list[str] = []
        for eid, path in mailbox_files(self.rt, source):
            if self.store.has(eid):
                skipped += 1
                continue
            try:
                raw = parse_email(eid, path.read_bytes())
            except ValueError:
                failed.append(eid)
                self.rt.audit.append("quarantine.parse_failed", {"business_id": self.business_id, "email_id": eid})
                continue
            if raw.sent_at and raw.sent_at.date() > today:
                later += 1
                continue
            pending.append(raw)
        pending.sort(key=lambda r: (r.sent_at.isoformat() if r.sent_at else "", r.email_id))
        done = [self.process(raw, "mailbox").email_id for raw in pending]
        self.rt.audit.append("inbox.synced", {"business_id": self.business_id, "processed": len(done),
                                              "skipped_existing": skipped, "not_yet_delivered": later,
                                              "failed": failed})
        return SyncReport(done, skipped, later, failed)

    def upload(self, data: bytes) -> InboxRecord:
        email_id = "up-" + secrets.token_hex(6)
        raw = parse_email(email_id, data)
        folder = upload_dir(self.rt, self.business_id)
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f"{email_id}.eml").write_bytes(data)
        return self.process(raw, "upload")

    def process(self, raw: RawEmail, source: str) -> InboxRecord:
        audit = self.rt.audit
        eid = raw.email_id
        audit.append("quarantine.received", {
            "business_id": self.business_id, "email_id": eid, "source": source, "sha256": raw.sha256,
            "from_domain": raw.from_domain, "reply_to_domain": raw.reply_to_domain, "auth": raw.auth,
            "attachments": [{"filename": a.filename, "kind": a.kind, "sha256": a.sha256} for a in raw.attachments],
        })

        extractions: list[Extraction] = [
            self.extractor.run("email", "email", email_message(raw.subject, raw.body_text), email_id=eid)]
        texts = [raw.subject, raw.body_text, *raw.html_hidden_text]
        hidden_reasons = ["html_hidden"] * bool(raw.html_hidden_text)
        attachments: list[AttachmentInfo] = []
        for a in raw.attachments:
            if a.kind == "pdf":
                pdf = extract_pdf_text(a.data)
                texts += [r.text for r in pdf.runs]
                hidden_reasons += [r.reason for r in pdf.hidden_runs if r.reason]
                x = self.extractor.run("invoice", a.filename, invoice_message(a.filename, pdf), email_id=eid)
                extractions.append(x)
                attachments.append(AttachmentInfo(filename=a.filename, kind=a.kind, sha256=a.sha256,
                                                  extraction=x.status, hidden_runs=len(pdf.hidden_runs)))
            elif a.kind == "image":
                x = self.extractor.run("receipt", a.filename, receipt_message(a.filename, a.content_type, a.data),
                                       email_id=eid)
                extractions.append(x)
                attachments.append(AttachmentInfo(filename=a.filename, kind=a.kind, sha256=a.sha256,
                                                  extraction=x.status))
            else:
                attachments.append(AttachmentInfo(filename=a.filename, kind=a.kind, sha256=a.sha256,
                                                  extraction="skipped"))
        signals = scan(*texts)

        today = self.rt.clock.today()
        with self.rt.business(self.business_id) as conn:
            directory, currency = self._directory(conn)
            fields, owner = build_fields(eid, extractions, Tokenizer(conn))
            conn.commit()
            seen = {}
            for r in self.store.all():
                if r.fields.invoice_number and (r.fields.invoice_number_from_document
                                                or r.fields.category in ("invoice", "overdue_notice")):
                    seen.setdefault(r.fields.invoice_number.value, r.email_id)
            headers = Headers(raw.from_address, raw.from_display_name, raw.from_domain, raw.reply_to_domain,
                              raw.sent_at.date() if raw.sent_at else None)
            report = assess(headers, fields, owner,
                            TextEvidence(signals.instruction_patterns,
                                         signals.urgency_patterns + signals.secrecy_patterns, tuple(hidden_reasons)),
                            directory, currency, _ledger_invoices(conn), seen, eid)
            feed, items = plan_items(eid, fields, report, directory, existing_items(conn), today)
            if items:
                write_items(conn, items)

        record = InboxRecord(
            email_id=eid, source=source, received_at=raw.sent_at,
            received_on=raw.sent_at.date() if raw.sent_at else None, processed_on=today, raw_sha256=raw.sha256,
            from_address=raw.from_address, from_display_name=raw.from_display_name,
            reply_to_address=raw.reply_to_address, subject=raw.subject[:200], auth=raw.auth,
            attachments=attachments, fields=fields, owner_view=owner, sentinel=report, feed=feed,
            scheduled_item_ids=[s.id for s in items])
        self.store.put(record)
        audit.append("sentinel.assessed", {
            "business_id": self.business_id, "email_id": eid, "sender_status": report.sender_status,
            "risk": report.risk, "hold": report.hold,
            "flags": [{"code": fl.code, "detected_by": fl.detected_by} for fl in report.flags],
            "recommended": report.recommended, "call_script": report.call_script is not None,
            "invalid_fields": list(fields.invalid_fields), "review_fields": list(fields.review_fields),
        })
        if feed != "not_applicable":
            audit.append("inbox.forecast_feed", {"business_id": self.business_id, "email_id": eid, "outcome": feed,
                                                 "scheduled_item_ids": [s.id for s in items]})
        return record


def load_inbox(rt: Runtime, business_id: str) -> list[InboxRecord]:
    path = rt.data_dir / business_id / "inbox.sqlite"
    return InboxStore(path).all() if path.is_file() else []

