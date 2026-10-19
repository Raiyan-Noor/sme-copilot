"""Onboarding from zero: a new business, its starting point, its files, its contacts, its inbox, its first brief.

The flow is scripted from the business's Skill Pack (data needs and advisor questions); no LLM decides anything here.
Every step reuses the path the rest of the app uses:
- bank and wallet CSVs: ledger.ingest.ingest_statement (the statement-upload path), PII tokenized there;
- products, per-product sales and ad spend CSVs: ledger/records.py, into the business's records folder;
- PDFs and receipt photos: the quarantined extractor and the sentinel (services/inbox.py), invariant 2. Their amounts
  stay pending until the owner approves them, and an approved amount keeps an untrusted source, so any action on
  it needs the owner's signature (invariant 3);
- starter limits: drafted here as suggestions only; the owner signs them in the browser (invariant 6);
- the first brief: services/overnight.py, through the Numeric Firewall (invariant 4).

Every step is in the audit log (invariant 7). Owner answers are stored as the pack option the owner picked, never as
free values, so an answer can only ever be a value the pack allows. A new business gets its own tenant SQLite and
records folder; seeded businesses are never touched (reset only deletes businesses created here).
"""

import gc
import hashlib
import json
import re
import secrets
import shutil
import sqlite3
from collections import defaultdict
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from app.engine.common import count, money
from app.engine.scheduled import scheduled_prefix
from app.firewall.digit_check import check_output
from app.firewall.fact import Fact
from app.firewall.store import FactStore
from app.ledger.ingest import IngestReport, RowError, StatementError, ingest_statement
from app.ledger.money import CURRENCY_EXPONENT, exponent
from app.ledger.pos import load_products_csv
from app.ledger.records import (
    NAME, RecordsError, detect_kind, parse_ad_spend, parse_products, parse_sales, read_csv, save_ad_spend,
    save_products, save_sales,
)
from app.ledger.schema import create_tenant, get_meta, tenant_path
from app.ledger.snapshot import load_snapshot
from app.packs.ledger_view import category_for
from app.packs.loader import list_pack_ids, load_pack
from app.packs.schema import AdvisorQuestion, DataNeed, Pack
from app.quarantine.mime import Attachment, RawEmail
from app.services.businesses import (
    META_ANSWERS, META_INBOX, META_NAME, META_ONBOARDED, META_PACK, META_SYNTHETIC, BusinessInfo, advisor_answers,
    business_info, records_folder, set_meta,
)

FALLBACK_PACK = "general_retail"
META_STATE = "onboarding_state"
CASH_BOOK = "Cash on hand"
OWNER_SOURCE = "owner_entered"  # scheduled items the owner typed in: trusted (agent/tools.TRUSTED_SCHEDULE_SOURCES)
DOCUMENT_SOURCE = "upload_approved"  # amounts from an uploaded document the owner approved: still untrusted
BILL_MONTHS = 3
MAX_UPLOAD_BYTES = 5 * 1024 * 1024
DOC_TYPES = {".pdf": "application/pdf", ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
             ".webp": "image/webp"}
# Sentinel flags that block approving a document's amount at onboarding. A first-time payee is expected for a new
# business (nobody has been paid yet), so it asks for a check instead of blocking.
BLOCKING_FLAGS = frozenset({"instruction_like_text", "hidden_text", "lookalike_domain", "display_name_spoof",
                            "bank_detail_change", "duplicate_invoice", "receipt_total_mismatch"})
DOMAIN = re.compile(r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)+$")

ContactKind = Literal["supplier", "customer", "payee"]


class OnboardingError(ValueError):
    """The request does not fit this business's onboarding (unknown question, bad option, bad name ...)."""


# ---- State --------------------------------------------------------------------------------------------------------

class UploadResult(BaseModel):
    """One file the owner dropped in. Counts are what the parser saw; `errors` explain a rejected file per line."""

    filename: str
    kind: Literal["bank", "sales", "products", "ad_spend", "invoice", "receipt", "unknown"]
    status: Literal["imported", "rejected", "pending_review", "flagged"]
    message: str
    rows: int = 0
    added: int = 0
    duplicates: int = 0
    date_from: date | None = None
    date_to: date | None = None
    ignored_columns: list[str] = []
    errors: list[RowError] = []
    document_id: str | None = None


class OnboardingState(BaseModel):
    skipped: list[str] = []  # data need IDs the owner skipped
    uploads: list[UploadResult] = []
    approved_documents: list[str] = []
    contacts_confirmed: bool = False
    finished: bool = False


def _state(conn: sqlite3.Connection) -> OnboardingState:
    raw = get_meta(conn, META_STATE)
    return OnboardingState.model_validate_json(raw) if raw else OnboardingState()


def _save_state(conn: sqlite3.Connection, state: OnboardingState) -> None:
    set_meta(conn, META_STATE, state.model_dump_json())


# ---- Step 1: create the business ----------------------------------------------------------------------------------

def match_pack(business_type: str) -> str:
    """The pack whose business_types appear in the owner's words; the general pack otherwise."""
    words = f" {re.sub(r'[^a-z ]+', ' ', business_type.lower())} "
    best, hits = FALLBACK_PACK, 0
    for pack_id in list_pack_ids():
        n = sum(f" {k}" in words for k in load_pack(pack_id).business_types)
        if n > hits:
            best, hits = pack_id, n
    return best


def _business_id(data_dir: Path, name: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:40] or "business"
    if not base[0].isalnum():
        base = "b" + base
    while True:
        candidate = f"{base}-{secrets.token_hex(2)}"
        if not tenant_path(data_dir, candidate).exists():
            return candidate


def create_business(rt, name: str, business_type: str, currency: str) -> BusinessInfo:
    name = " ".join(name.split())
    if not NAME.match(name):
        raise OnboardingError("the business name may use letters, digits, spaces and . , ' & - only (up to 60)")
    if currency not in CURRENCY_EXPONENT:
        raise OnboardingError(f"unsupported currency {currency!r}")
    rt.ensure_ready()
    pack_id = match_pack(business_type)
    business_id = _business_id(rt.data_dir, name)
    conn = create_tenant(tenant_path(rt.data_dir, business_id), business_id, currency)
    try:
        set_meta(conn, META_NAME, name)
        set_meta(conn, META_PACK, pack_id)
        # A demo build: every business here runs on synthetic data and is labelled so.
        set_meta(conn, META_SYNTHETIC, "true")
        set_meta(conn, META_ONBOARDED, "true")
        _save_state(conn, OnboardingState())
        info = business_info(conn)
    finally:
        conn.close()
    _write_contacts(rt, business_id, {"owner": {"name": "the owner"}})
    rt.audit.append("onboarding.business_created", {"business_id": business_id, "pack_id": pack_id,
                                                     "currency": currency, "matched_from_type": pack_id != FALLBACK_PACK})
    return info


@contextmanager
def _onboarded(rt, business_id: str) -> Iterator[sqlite3.Connection]:
    """Open an onboarded business, refusing seeded ones: onboarding never writes to Maya's or the fashion shop."""
    with rt.business(business_id) as conn:
        if not business_info(conn).onboarded:
            raise OnboardingError("this business was not created by onboarding")
        yield conn


def _records(rt, conn: sqlite3.Connection) -> Path:
    folder = records_folder(conn, rt.settings.seed_dir)
    assert folder is not None
    folder.mkdir(parents=True, exist_ok=True)
    return folder


# ---- Step 2: starting point ---------------------------------------------------------------------------------------

class Bill(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    kind: Literal["bill", "loan"] = "bill"
    amount_minor: int = Field(gt=0, le=10**12)
    day_of_month: int = Field(ge=1, le=28)


def _plain(minor: int, currency: str) -> str:
    """Minor units as a plain decimal for a CSV row the ledger ingests ("1234.50")."""
    e = exponent(currency)
    return f"{minor / 10**e:.{e}f}" if e else str(minor)


def _csv_cell(text: str) -> str:
    return '"' + text.replace('"', '""') + '"'


def set_starting_point(rt, business_id: str, cash_minor: int | None, bills: list[Bill]) -> dict:
    """Cash on hand becomes a running-balance row in a cash book (so earlier receipts stay history and do not change
    it); each regular bill or loan payment becomes monthly payables for the next months, from a payee the owner
    named. Both go through the ledger's own ingestion and scheduled-items table."""
    with _onboarded(rt, business_id) as conn:
        today = rt.clock.today()
        currency = get_meta(conn, "currency")
        report = None
        if cash_minor is not None:
            if cash_minor < 0:
                raise OnboardingError("cash on hand cannot be negative")
            amount = _plain(cash_minor, currency)
            yesterday = (today - timedelta(days=1)).isoformat()
            if cash_minor > 0:
                csv_text = (f"date,description,amount,balance\n{yesterday},{_csv_cell('Cash on hand at setup')},"
                            f"{amount},{amount}\n")
                report = ingest_statement(conn, csv_text, source_name="setup: cash on hand", account_number=CASH_BOOK,
                                          account_name=CASH_BOOK)
        contacts = _read_contacts(rt, business_id, conn)
        items = []
        for bill in bills:
            name = " ".join(bill.name.split())
            if not NAME.match(name):
                raise OnboardingError(f"bill name {name[:30]!r} has characters that are not allowed")
            payee_id = _contact_id("payee", name)
            if not any(p["id"] == payee_id for p in contacts.setdefault("payees", [])):
                contacts["payees"].append({"id": payee_id, "name": name, "category": _bill_category(rt, conn,
                                                                                                     bill.kind)})
            due = _next_day_of_month(today, bill.day_of_month)
            for n in range(BILL_MONTHS):
                d = _add_months(due, n)
                items.append((f"OWN-{payee_id.upper()}-{d.isoformat()}", "payable", _bill_category(rt, conn, bill.kind),
                              d.isoformat(), bill.amount_minor, "open", payee_id, f"{name} {d:%b %Y}", OWNER_SOURCE))
        with conn:
            conn.executemany(
                "INSERT OR REPLACE INTO scheduled_items (id, kind, category, due_date, amount_minor, status,"
                " counterparty_id, reference, source) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", items)
        _write_contacts(rt, business_id, contacts, conn)
    rt.audit.append("onboarding.starting_point", {"business_id": business_id, "cash_on_hand": cash_minor is not None,
                                                   "bills": len(bills), "scheduled_items": len(items)})
    if report is not None:
        rt.audit.append("ledger.statement_ingested", {"business_id": business_id, **report.model_dump(mode="json")})
    return {"scheduled_items": len(items)}


def _bill_category(rt, conn: sqlite3.Connection, kind: str) -> str:
    pack = load_pack(business_info(conn).pack_id)
    if kind == "loan" and "loan_repayment" in pack.categories:
        return "loan_repayment"
    for preferred in ("rent", "utilities"):
        if preferred in pack.categories:
            return preferred
    return next(c for c, v in pack.categories.items() if v.kind == "operating")


def _next_day_of_month(today: date, day: int) -> date:
    d = today.replace(day=day)
    return d if d >= today else _add_months(d, 1)


def _add_months(d: date, n: int) -> date:
    month = d.month - 1 + n
    return d.replace(year=d.year + month // 12, month=month % 12 + 1)


# ---- Step 3: advisor questions and data needs ---------------------------------------------------------------------

def answer(rt, business_id: str, question_id: str, option: int) -> float | None:
    """Store the owner's pick. Only an option the pack offers can be stored (the value comes from the pack)."""
    with _onboarded(rt, business_id) as conn:
        pack = load_pack(business_info(conn).pack_id)
        q = next((q for q in pack.advisor_questions if q.id == question_id), None)
        if q is None or not 0 <= option < len(q.options):
            raise OnboardingError("unknown question or option")
        answers = advisor_answers(conn)
        answers[question_id] = q.options[option].value
        set_meta(conn, META_ANSWERS, json.dumps(answers, sort_keys=True))
    rt.audit.append("onboarding.answered", {"business_id": business_id, "question": question_id, "option": option,
                                            "effect": q.effect.model_dump(exclude_none=True),
                                            "not_sure": q.options[option].value is None})
    return q.options[option].value


def skip_need(rt, business_id: str, need_id: str) -> None:
    with _onboarded(rt, business_id) as conn:
        pack = load_pack(business_info(conn).pack_id)
        if need_id not in {n.id for n in pack.data_needs}:
            raise OnboardingError("unknown data need")
        state = _state(conn)
        if need_id not in state.skipped:
            state.skipped.append(need_id)
        _save_state(conn, state)
    rt.audit.append("onboarding.skipped", {"business_id": business_id, "need": need_id})


# ---- Step 4: uploads ----------------------------------------------------------------------------------------------

def upload(rt, business_id: str, filename: str, data: bytes) -> UploadResult:
    """Detect what a file is and send it down the path the app already uses for it."""
    filename = Path(filename or "upload").name[:120]
    if len(data) > MAX_UPLOAD_BYTES:
        result = UploadResult(filename=filename, kind="unknown", status="rejected",
                              message=f"The file is larger than {MAX_UPLOAD_BYTES // (1024 * 1024)} MB.")
        return _record_upload(rt, business_id, result)
    suffix = Path(filename).suffix.lower()
    if suffix in DOC_TYPES:
        result = _upload_document(rt, business_id, filename, DOC_TYPES[suffix], data)
    else:
        result = _upload_csv(rt, business_id, filename, data)
    return _record_upload(rt, business_id, result)


def _record_upload(rt, business_id: str, result: UploadResult) -> UploadResult:
    with _onboarded(rt, business_id) as conn:
        state = _state(conn)
        state.uploads.append(result)
        if result.status == "imported":
            pack = load_pack(business_info(conn).pack_id)
            done = {n.id for n in pack.data_needs if n.kind == result.kind}
            state.skipped = [s for s in state.skipped if s not in done]
        _save_state(conn, state)
    rt.audit.append("onboarding.upload", {"business_id": business_id, "kind": result.kind, "status": result.status,
                                          "rows": result.rows, "added": result.added, "errors": len(result.errors),
                                          "document_id": result.document_id})
    return result


def _rejected(filename: str, kind, errors: list[RowError], message: str = "Nothing was imported.") -> UploadResult:
    return UploadResult(filename=filename, kind=kind, status="rejected", message=message, errors=errors[:50])


def _upload_csv(rt, business_id: str, filename: str, data: bytes) -> UploadResult:
    try:
        header, _ = read_csv(data)
    except RecordsError as e:
        return _rejected(filename, "unknown", e.errors)
    kind = detect_kind(header)
    if kind is None:
        return _rejected(filename, "unknown", [RowError(line=1, message="columns not recognised")],
                         "I could not tell what this file is. I read bank statements (date, description, amount), "
                         "products (name, cost, price, stock), sales (date, product, qty, amount) and ad spend "
                         "(date, campaign, spend).")
    with _onboarded(rt, business_id) as conn:
        currency = get_meta(conn, "currency")
        if kind == "bank":
            stem = re.sub(r"[^A-Za-z ]+", " ", Path(filename).stem).strip() or "Statement"
            try:
                report: IngestReport = ingest_statement(conn, data, source_name=filename, account_number=stem,
                                                        account_name=f"{stem.title()} (uploaded statement)")
            except StatementError as e:
                rt.audit.append("ledger.statement_rejected", {"business_id": business_id, "errors": len(e.errors)})
                return _rejected(filename, "bank", e.errors)
            rt.audit.append("ledger.statement_ingested", {"business_id": business_id,
                                                          **report.model_dump(mode="json")})
            return UploadResult(filename=filename, kind="bank", status="imported", rows=report.rows,
                                added=report.inserted, duplicates=report.duplicates, date_from=report.date_from,
                                date_to=report.date_to, ignored_columns=report.ignored_columns,
                                message="Statement imported.")
        folder = _records(rt, conn)
        try:
            if kind == "products":
                products = parse_products(data, currency)
                added, updated = save_products(folder, products)
                return UploadResult(filename=filename, kind=kind, status="imported", rows=len(products), added=added,
                                    duplicates=updated, message="Products saved.")
            if kind == "sales":
                existing = load_products_csv(folder / "products.csv") if (folder / "products.csv").is_file() else ()
                lines = parse_sales(data, currency, existing)
                added, dup = save_sales(folder, lines)
                return UploadResult(filename=filename, kind=kind, status="imported", rows=len(lines), added=added,
                                    duplicates=dup, date_from=lines[0].date, date_to=lines[-1].date,
                                    message="Sales saved.")
            lines = parse_ad_spend(data, currency)
            added, dup = save_ad_spend(folder, lines)
            return UploadResult(filename=filename, kind="ad_spend", status="imported", rows=len(lines), added=added,
                                duplicates=dup, date_from=lines[0].date, date_to=lines[-1].date,
                                message="Ad spend saved.")
        except RecordsError as e:
            return _rejected(filename, kind, e.errors)


def _upload_document(rt, business_id: str, filename: str, content_type: str, data: bytes) -> UploadResult:
    """Quarantine: the extractor reads it (no tools), the sentinel judges the typed fields. Nothing is posted."""
    from app.services.inbox import InboxProcessor  # services.inbox imports the runtime; keep this module light

    kind = "invoice" if content_type == "application/pdf" else "receipt"
    email_id = "up-" + secrets.token_hex(6)
    with rt.business(business_id) as conn:
        name = business_info(conn).name
    raw = RawEmail(email_id=email_id, sha256=hashlib.sha256(data).hexdigest(), from_address="",
                   from_display_name=f"{name} (uploaded by the owner)", reply_to_address=None, subject=filename,
                   sent_at=datetime.combine(rt.clock.today(), time(9, 0)), auth={}, body_text="",
                   attachments=[Attachment(filename=filename, content_type=content_type, data=data)])
    folder = rt.data_dir / business_id / "inbox_uploads"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{email_id}{Path(filename).suffix.lower()}").write_bytes(data)
    record = InboxProcessor(rt, business_id).process(raw, "upload")
    codes = {f.code for f in record.sentinel.flags}
    blocked = codes & BLOCKING_FLAGS
    status = "flagged" if blocked else "pending_review"
    message = ("Held: " + ", ".join(sorted(c.replace("_", " ") for c in blocked)) + ". I will not use its amounts."
               if blocked else "Read. Check the amount and approve it before I use it.")
    if not record.fields.amount_minor and not blocked:
        message = "Read, but I could not find an amount. Nothing to approve."
    return UploadResult(filename=filename, kind=kind, status=status, message=message, document_id=email_id)


def document_view(rt, business_id: str, email_id: str):
    from app.services.inbox import store_for

    record = store_for(rt, business_id).get(email_id)
    if record is None or record.source != "upload":
        raise OnboardingError("unknown document")
    return record


def approve_document(rt, business_id: str, email_id: str) -> dict:
    """Use an uploaded document's amount: an invoice becomes a payable to its supplier, a receipt an expense in the
    cash book. Refused if the sentinel flagged it. The new row's source stays untrusted (invariant 3)."""
    record = document_view(rt, business_id, email_id)
    blocked = {f.code for f in record.sentinel.flags} & BLOCKING_FLAGS
    if blocked:
        raise OnboardingError("this document was flagged: " + ", ".join(sorted(blocked)))
    f = record.fields
    if f.amount_minor is None:
        raise OnboardingError("no amount was read from this document")
    with _onboarded(rt, business_id) as conn:
        state = _state(conn)
        if email_id in state.approved_documents:
            raise OnboardingError("already approved")
        today = rt.clock.today()
        owner = record.owner_view
        who = owner.supplier_name or owner.payee_name or owner.merchant_name or "Supplier"
        who = " ".join(re.sub(r"[^\w &'.,\-]+", " ", who).split())[:60] or "Supplier"
        if f.has_receipt:
            # A receipt is money already spent: the owner's cash-on-hand figure (dated yesterday) already reflects
            # it, so it goes in the day before that, as recent spending, never as a second deduction from today.
            spent_on = today - timedelta(days=2)
            amount = _plain(f.amount_minor.value, get_meta(conn, "currency"))
            csv_text = f"date,description,amount\n{spent_on.isoformat()},{_csv_cell('Receipt: ' + who)},-{amount}\n"
            ingest_statement(conn, csv_text, source_name=f"receipt {email_id}", account_number=CASH_BOOK,
                             account_name=CASH_BOOK)
            result = {"posted": "expense"}
        else:
            contacts = _read_contacts(rt, business_id, conn)
            supplier_id = _contact_id("supplier", who)
            if not any(s["id"] == supplier_id for s in contacts.setdefault("suppliers", [])):
                contacts["suppliers"].append({"id": supplier_id, "name": who, "bank_accounts": []})
                _write_contacts(rt, business_id, contacts, conn)
            pack = load_pack(business_info(conn).pack_id)
            category = next(c for c, v in pack.categories.items() if v.kind == "cogs")
            due = f.due_date.value if f.due_date else today + timedelta(days=30)
            item_id = f"UPL-{email_id.upper()}"
            with conn:
                conn.execute(
                    "INSERT OR IGNORE INTO scheduled_items (id, kind, category, due_date, amount_minor, status,"
                    " counterparty_id, reference, source) VALUES (?, 'payable', ?, ?, ?, 'open', ?, ?, ?)",
                    (item_id, category, due.isoformat(), f.amount_minor.value, supplier_id,
                     f.invoice_number.value if f.invoice_number else None, DOCUMENT_SOURCE))
            result = {"posted": "payable", "scheduled_item_id": item_id}
        state.approved_documents.append(email_id)
        _save_state(conn, state)
    rt.audit.append("onboarding.document_approved", {"business_id": business_id, "email_id": email_id,
                                                     "provenance": "untrusted", **result})
    return result


# ---- Step 4b: contacts --------------------------------------------------------------------------------------------

class ContactProposal(BaseModel):
    id: str
    name: str
    kind: ContactKind
    source: Literal["statement", "document", "bill"]
    seen: int
    domain: str | None = None
    confirmed: bool = False


class ContactIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    kind: ContactKind
    domain: str | None = Field(default=None, max_length=120)


def _contact_id(kind: str, name: str) -> str:
    prefix = {"supplier": "sup", "customer": "cus", "payee": "pay"}[kind]
    return f"{prefix}_" + (re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")[:40] or "x")


def _contacts_path(rt, business_id: str) -> Path:
    return rt.data_dir / business_id / "records" / "counterparties.json"


def _read_contacts(rt, business_id: str, conn: sqlite3.Connection | None = None) -> dict:
    path = _contacts_path(rt, business_id)
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


def _write_contacts(rt, business_id: str, doc: dict, conn: sqlite3.Connection | None = None) -> None:
    path = _contacts_path(rt, business_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(doc, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def contact_proposals(rt, business_id: str) -> list[ContactProposal]:
    """Who the uploads suggest the business deals with: the busiest statement counterparties and the suppliers on
    documents the sentinel did not flag. Names are shown to the owner; only the ones the owner confirms become
    known contacts (and only then can the planner see them, as validated short names)."""
    from app.services.inbox import load_inbox

    with rt.business(business_id) as conn:
        pack = load_pack(business_info(conn).pack_id)
        contacts = _read_contacts(rt, business_id, conn)
        snapshot = load_snapshot(conn)
    known = {c["id"] for group in ("suppliers", "customers", "payees") for c in contacts.get(group, [])}
    seen: dict[str, list[ContactKind]] = defaultdict(list)
    for t in snapshot.transactions:
        if t.counterparty and (kind := _contact_kind(pack, t)) is not None:
            seen[" ".join(t.counterparty.split())].append(kind)
    out: dict[str, ContactProposal] = {}
    for name, ks in sorted(seen.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        if not NAME.match(name) or "tok_" in name.lower() or len(out) >= 10:
            continue
        kind = max(set(ks), key=lambda k: (ks.count(k), k))
        cid = _contact_id(kind, name)
        out[cid] = ContactProposal(id=cid, name=name, kind=kind, source="statement", seen=len(ks),
                                   confirmed=cid in known)
    for record in load_inbox(rt, business_id):
        if record.source != "upload" or {f.code for f in record.sentinel.flags} & BLOCKING_FLAGS:
            continue
        name = record.owner_view.supplier_name or record.owner_view.payee_name
        if not name or not record.fields.has_invoice_document:
            continue
        name = " ".join(re.sub(r"[^\w &'.,\-]+", " ", name).split())[:60]
        if not NAME.match(name):
            continue
        cid = _contact_id("supplier", name)
        prev = out.get(cid)
        out[cid] = ContactProposal(id=cid, name=name, kind="supplier", source="document",
                                   seen=(prev.seen if prev else 0) + 1, confirmed=cid in known)
    for p in contacts.get("payees", []):
        out.setdefault(p["id"], ContactProposal(id=p["id"], name=p["name"], kind="payee", source="bill", seen=1,
                                                confirmed=True))
    return list(out.values())


# Statement rows that are not a business the owner deals with: walk-in sales channels, refunds, own transfers,
# owner drawings, wages and payment fees.
NOT_A_CONTACT = frozenset({"payroll", "payment_fees", "customer_refunds"})


def _contact_kind(pack: Pack, t) -> ContactKind | None:
    """What a statement counterparty is, from the pack's categorization of the row (None: not a contact)."""
    cid = category_for(t, pack)
    cat = pack.categories.get(cid)
    if cat is None or cid in NOT_A_CONTACT or cat.kind in ("transfer", "owner", "opening"):
        return None
    if cat.kind == "revenue":
        return "customer" if cat.scheduled and t.amount_minor > 0 else None  # invoiced customers, not walk-ins
    if cat.kind == "operating" and cat.scheduled:
        return "payee"
    return "supplier"


def confirm_contacts(rt, business_id: str, contacts_in: list[ContactIn]) -> int:
    with _onboarded(rt, business_id) as conn:
        doc = _read_contacts(rt, business_id, conn)
        added = 0
        for c in contacts_in:
            name = " ".join(c.name.split())
            if not NAME.match(name):
                raise OnboardingError(f"contact name {name[:30]!r} has characters that are not allowed")
            domain = (c.domain or "").strip().lower() or None
            if domain and not DOMAIN.match(domain):
                raise OnboardingError(f"{domain!r} is not a domain name")
            group = {"supplier": "suppliers", "customer": "customers", "payee": "payees"}[c.kind]
            cid = _contact_id(c.kind, name)
            entries = doc.setdefault(group, [])
            if any(e["id"] == cid for e in entries):
                continue
            entry = {"id": cid, "name": name}
            if domain:
                entry["domain"] = domain
            if c.kind == "supplier":
                entry["bank_accounts"] = []
            entries.append(entry)
            added += 1
        if doc.get("owner", {}).get("name") in (None, "the owner"):
            doc["owner"] = {"name": "the owner"}
        _write_contacts(rt, business_id, doc, conn)
        state = _state(conn)
        state.contacts_confirmed = True
        _save_state(conn, state)
    rt.audit.append("onboarding.contacts_confirmed", {"business_id": business_id, "added": added,
                                                      "kinds": sorted({c.kind for c in contacts_in})})
    return added


# ---- Step 5: inbox ------------------------------------------------------------------------------------------------

def set_inbox(rt, business_id: str, connection: Literal["sandbox", "gmail"]) -> str:
    if connection == "gmail":
        raise OnboardingError("Gmail is not connected in this build yet; use the sandbox inbox")
    with _onboarded(rt, business_id) as conn:
        set_meta(conn, META_INBOX, connection)
    rt.audit.append("onboarding.inbox_connected", {"business_id": business_id, "connection": connection})
    return connection


# ---- Step 6: starter limits (suggestions only; the owner signs in the browser) ------------------------------------

class SuggestedMandate(BaseModel):
    tool: str
    title: str
    text: str  # template text with {fact:id} placeholders
    max_amount_minor: int
    allowlist: list[str]
    names: list[str]


def suggest_mandates(rt, business_id: str, store: FactStore) -> list[SuggestedMandate]:
    """Up to two limits the data supports: pay the owner's regular bills (largest three under the policy cap), and
    remind customers with open invoices. Each cap is a Fact citing the bills it covers."""
    from app.agent.tools import TRUSTED_SCHEDULE_SOURCES

    computed = rt.facts(business_id)
    policy = rt.gateway(business_id).policy
    names = {c["id"]: c["name"] for group in ("suppliers", "customers", "payees")
             for c in _read_contacts(rt, business_id).get(group, [])}
    currency = computed.inputs.info.currency
    today = rt.clock.today()
    out = []
    for tool, kind, title, verb in (("pay_recurring_bill", "payable", "Pay regular bills", "Pay"),
                                    ("send_invoice_reminder", "receivable", "Remind customers", "Remind")):
        rule = policy.t2.get(tool)
        if rule is None:
            continue
        biggest: dict[str, tuple[int, list[str]]] = {}
        for s in computed.inputs.scheduled:
            if s.kind != kind or s.status != "open" or not s.counterparty_id or s.source not in TRUSTED_SCHEDULE_SOURCES \
                    or s.due_date < today or s.amount_minor > rule.max_amount_minor:
                continue
            amount, ids = biggest.get(s.counterparty_id, (0, []))
            biggest[s.counterparty_id] = (max(amount, s.amount_minor), ids + [s.id])
        top = sorted(biggest, key=lambda c: (-biggest[c][0], c))[:3]
        if not top:
            continue
        cap = max(biggest[c][0] for c in top)
        fid = f"onboarding.suggested_cap.{tool}"
        store.add(money(fid, cap, currency, "services.onboarding.suggest_mandates",
                        [i for c in top for i in biggest[c][1]]))
        who = [names.get(c, c) for c in top]
        noun = "each bill" if kind == "payable" else "each invoice"
        text = f"{verb} {', '.join(who)} up to {{fact:{fid}}} {noun}, without asking you first."
        out.append(SuggestedMandate(tool=tool, title=title, text=text, max_amount_minor=cap, allowlist=top,
                                    names=who))
    return out


# ---- Summary, finish and the to-do list ---------------------------------------------------------------------------

class SummaryLine(BaseModel):
    label: str
    text: str  # template text with {fact:id} placeholders


class Plan(BaseModel):
    """What onboarding asks for this business, from its pack."""

    pack_id: str
    pack_name: str
    data_needs: list[DataNeed]
    questions: list[AdvisorQuestion]


class OnboardingView(BaseModel):
    business: BusinessInfo
    plan: Plan
    answers: dict[str, float | None]
    state: OnboardingState
    inbox: str | None
    contacts: list[ContactProposal]
    summary: list[SummaryLine]
    could_also_check: list[str]
    mandates: list[SuggestedMandate]
    facts: dict[str, Fact]


def _plan(pack: Pack) -> Plan:
    return Plan(pack_id=pack.id, pack_name=pack.display_name, data_needs=list(pack.data_needs),
                questions=list(pack.advisor_questions))


def could_also_check(pack: Pack, skipped: list[str]) -> list[str]:
    return [f"I could also check {n.unlocks} if you add {n.label}." for n in pack.data_needs if n.id in skipped]


def skipped_hints(rt, business_id: str) -> list[str]:
    """For the brief: what the owner skipped at onboarding and what adding it would unlock (empty for seeds)."""
    with rt.business(business_id) as conn:
        info = business_info(conn)
        if not info.onboarded:
            return []
        return could_also_check(load_pack(info.pack_id), _state(conn).skipped)


def view(rt, business_id: str) -> OnboardingView:
    with rt.business(business_id) as conn:
        info = business_info(conn)
        if not info.onboarded:
            raise OnboardingError("this business was not created by onboarding")
        state, answers = _state(conn), advisor_answers(conn)
        inbox = get_meta(conn, META_INBOX)
    pack = load_pack(info.pack_id)
    store = FactStore()
    summary = _summary(rt, business_id, info, pack, answers, state, store)
    mandates = suggest_mandates(rt, business_id, store)
    view = OnboardingView(business=info, plan=_plan(pack), answers=answers, state=state, inbox=inbox,
                          contacts=contact_proposals(rt, business_id), summary=summary,
                          could_also_check=could_also_check(pack, state.skipped), mandates=mandates,
                          facts={f.id: f for f in store})
    _firewall(view)
    return view


def _firewall(view: OnboardingView) -> None:
    """Invariant 4: summary and mandate text carry numbers only as placeholders of facts in the view."""
    known = FactStore()
    known.add_all(view.facts.values())
    for text in [s.text for s in view.summary] + [m.text for m in view.mandates] + view.could_also_check:
        result = check_output(text, known)
        if not result.ok:
            raise RuntimeError(f"onboarding text failed the Numeric Firewall: {[v.kind.value for v in result.violations]}")


def _summary(rt, business_id: str, info: BusinessInfo, pack: Pack, answers: dict, state: OnboardingState,
             store: FactStore) -> list[SummaryLine]:
    computed = rt.facts(business_id)
    pool = computed.store
    lines = [SummaryLine(label="Business", text=f"{_digit_free(info.name)}, run with the {pack.display_name} "
                                                f"Skill Pack.")]

    def cite(fid: str) -> str | None:
        if fid not in pool:
            return None
        store.add(pool.get(fid))
        return "{fact:" + fid + "}"

    if (bal := cite("cash.balance")) is not None and computed.inputs.snapshot.transactions:
        lines.append(SummaryLine(label="Cash", text=f"Cash across your accounts: {bal}."))
    txns = computed.inputs.snapshot.transactions
    if txns:
        store.add(count("onboarding.transactions", len(txns), "services.onboarding.summary", [t.id for t in txns]))
        lines.append(SummaryLine(label="Ledger", text="Transactions I can see: {fact:onboarding.transactions}."))
    if computed.inputs.products:
        store.add(count("onboarding.products", len(computed.inputs.products), "services.onboarding.summary",
                        [f"product:{p.id}" for p in computed.inputs.products]))
        lines.append(SummaryLine(label="Products", text="Products on file: {fact:onboarding.products}."))
    if computed.inputs.ad_spend:
        lines.append(SummaryLine(label="Ads", text=f"Ad campaigns: {_campaign_names(computed)}, total spend "
                                                   f"{cite('ads.total_spend')}."))
    bills = [s for s in computed.inputs.scheduled if s.source == OWNER_SOURCE and s.kind == "payable"]
    names = {c["id"]: c["name"] for c in _read_contacts(rt, business_id).get("payees", [])}
    for payee in sorted({s.counterparty_id for s in bills}):
        first = min((s for s in bills if s.counterparty_id == payee), key=lambda s: s.due_date)
        p = scheduled_prefix(first.id)
        amount, due = cite(f"{p}.amount"), cite(f"{p}.due_date")
        if amount and due:
            lines.append(SummaryLine(label="Bill", text=f"{_digit_free(names.get(payee, 'Bill'))}: {amount}, "
                                                        f"next due {due}."))
    told = [q for q in pack.advisor_questions if q.id in answers]
    for q in told:
        value = answers[q.id]
        if value is None:
            continue
        option = next((o.label for o in q.options if o.value == value), None)
        if q.effect.fact and (fid := cite(f"owner.{q.effect.fact}")):
            lines.append(SummaryLine(label="You told me", text=f"{_digit_free(q.ask.split('?')[0])}: {fid}."))
        elif option is not None:
            lines.append(SummaryLine(label="You told me", text=f"{_digit_free(q.ask.split('?')[0])}: noted, I "
                                                               f"adjusted my checks to it."))
    return lines


def _campaign_names(computed) -> str:
    from app.agent.context import safe_label

    return ", ".join(safe_label(c.name) for c in computed.ads.campaigns[:4])


def _digit_free(text: str) -> str:
    from app.agent.context import safe_label

    return safe_label(text, 120)


class FinishResult(BaseModel):
    business: BusinessInfo
    todo: list[str]
    could_also_check: list[str]


def finish(rt, business_id: str) -> FinishResult:
    """Mark onboarding done and write the first brief now (no reminders: nothing is overdue on day one)."""
    from app.services.overnight import run_overnight

    with _onboarded(rt, business_id) as conn:
        state = _state(conn)
        state.finished = True
        _save_state(conn, state)
        info = business_info(conn)
        inbox = get_meta(conn, META_INBOX)
    report = run_overnight(rt, business_id, reminders=False)
    computed = rt.facts(business_id)
    pack = load_pack(info.pack_id)
    todo = []
    if computed.leaks:
        todo.append("Look at the biggest leak in your brief and decide what to do about it.")
    if computed.ads.losing:
        todo.append("Review the ad campaigns that cost more than they bring in.")
    if computed.products.stockout_risk:
        todo.append("Reorder the products that are about to run out.")
    pending_docs = [u for u in state.uploads if u.status == "pending_review"
                    and u.document_id not in state.approved_documents]
    if pending_docs:
        todo.append("Approve the amounts I read from your documents, so I can plan for them.")
    if any(u.status == "flagged" for u in state.uploads):
        todo.append("Open the flagged document in your inbox and check it with the sender by phone.")
    if not rt.gateway(business_id).store.has_owner_key():
        todo.append("Sign a limit so I can pay small regular bills on time without asking.")
    if inbox is None:
        todo.append("Connect your inbox so I can read invoices as they arrive.")
    if not state.contacts_confirmed:
        todo.append("Confirm your suppliers and customers so I can spot fake ones.")
    rt.audit.append("onboarding.finished", {"business_id": business_id, "brief_generated_by":
                                            report.brief.generated_by, "todo": len(todo),
                                            "skipped": state.skipped})
    return FinishResult(business=info, todo=todo, could_also_check=could_also_check(pack, state.skipped))


# ---- Reset (rehearsals) -------------------------------------------------------------------------------------------

def delete_business(rt, business_id: str) -> None:
    """Delete one business created by onboarding: its tenant file and folder. Seeded businesses are refused."""
    with rt.business(business_id) as conn:
        if not business_info(conn).onboarded:
            raise OnboardingError("only businesses created by onboarding can be deleted")
    rt.forget(business_id)
    gc.collect()  # per-call SQLite connections (inbox store) close when collected; Windows keeps open files
    (rt.data_dir / f"{business_id}.sqlite").unlink(missing_ok=True)
    shutil.rmtree(rt.data_dir / business_id, ignore_errors=True)
    rt.audit.append("onboarding.business_deleted", {"business_id": business_id})


def reset(rt) -> list[str]:
    """Delete every business created by onboarding, for a clean rehearsal. Returns the deleted IDs."""
    from app.services.businesses import list_businesses

    rt.ensure_ready()
    gone = [b.id for b in list_businesses(rt.data_dir) if b.onboarded]
    for business_id in gone:
        delete_business(rt, business_id)
    return gone
