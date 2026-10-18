"""The only shape in which extracted content leaves quarantine: validated, provenance-tagged fields.

Invariant 2: every value here is an enum, a bool, an integer, a date, or a short string that passed a strict
pattern (invoice/PO numbers). There is no subject, body, summary or free-text name; payee names and line items
exist only in the owner's view (`OwnerView`), never in `DocumentFields`.
Invariant 3: every extracted value is wrapped in `Untrusted`, so anything built from it carries
provenance="untrusted" and forces owner approval if it ever reaches an action.

Account numbers are PII: they are tokenized with the tenant's key (the same tokens the ledger uses, so they can be
compared with payment history) and only the last four characters are kept for the owner's screen.
"""

import re
from datetime import date
from typing import Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict

from app.ledger.pii import PiiKind, Tokenizer, normalize
from app.quarantine.extractor import Extraction
from app.quarantine.schemas import (Day, EmailCategory, EmailExtraction, InvoiceExtraction, Money, PoDirection,
                                    ReceiptExtraction, Text)

REVIEW_BELOW = 0.7  # extractor.md rule 8: below this confidence a field goes to human review

T = TypeVar("T")

REF_PATTERN = re.compile(r"^[A-Z0-9][A-Z0-9\-/_.]{1,39}$")
ACCOUNT_PATTERN = re.compile(r"^[A-Z0-9]{4,34}$")
CURRENCY_PATTERN = re.compile(r"^[A-Z]{3}$")


class Untrusted(BaseModel, Generic[T]):
    """A value read from untrusted content. `source` says which document it came from."""

    model_config = ConfigDict(frozen=True)

    value: T
    provenance: Literal["untrusted"] = "untrusted"
    source: str
    confidence: float
    needs_review: bool


class PromiseField(BaseModel):
    model_config = ConfigDict(frozen=True)

    date: Untrusted[date]
    amount_minor: Untrusted[int] | None


class DocumentFields(BaseModel):
    """Everything downstream code (sentinel, forecast feed, planner tool) may use from one email and its files."""

    model_config = ConfigDict(frozen=True)

    category: EmailCategory | None = None
    has_invoice_document: bool = False
    has_receipt: bool = False
    currency: str | None = None
    amount_minor: Untrusted[int] | None = None
    email_amount_minor: Untrusted[int] | None = None  # amount stated in the body, when a document also has one
    due_date: Untrusted[date] | None = None
    invoice_number: Untrusted[str] | None = None
    invoice_number_from_document: bool = False
    referenced_invoice_numbers: tuple[str, ...] = ()
    po_number: Untrusted[str] | None = None
    po_direction: PoDirection | None = None
    start_date: Untrusted[date] | None = None  # invoice or delivery date, for terms-based due dates
    payment_terms_days: Untrusted[int] | None = None
    payee_account_token: Untrusted[str] | None = None
    payee_account_last4: str | None = None
    asks_to_change_bank_details: bool = False
    marked_overdue: bool = False
    promises: tuple[PromiseField, ...] = ()
    line_items_sum_minor: int | None = None
    stated_total_minor: int | None = None
    cash_tendered_minor: int | None = None
    change_minor: int | None = None
    model_totals_mismatch: bool = False
    model_instruction_flag: bool = False
    model_instruction_category: str | None = None
    model_urgency: bool = False
    model_secrecy: bool = False
    extraction_status: dict[str, str] = {}
    invalid_fields: tuple[str, ...] = ()
    review_fields: tuple[str, ...] = ()


class OwnerView(BaseModel):
    """Display-only strings for the owner's screen. Never passed to the planner (invariant 2)."""

    payee_name: str | None = None
    payee_bank_name: str | None = None
    merchant_name: str | None = None
    supplier_name: str | None = None
    line_items: list[tuple[str, int | None]] = []


class _Builder:
    def __init__(self, tokenizer: Tokenizer | None):
        self.tok = tokenizer
        self.invalid: list[str] = []
        self.review: list[str] = []

    def _wrap(self, name: str, value, confidence: float, source: str):
        if confidence < REVIEW_BELOW:
            self.review.append(name)
        return Untrusted(value=value, source=source, confidence=round(confidence, 3),
                         needs_review=confidence < REVIEW_BELOW)

    def money(self, name: str, f: Money | None, source: str) -> Untrusted[int] | None:
        if f is None or f.amount_minor is None:
            return None
        if f.amount_minor <= 0:
            self.invalid.append(name)
            return None
        return self._wrap(name, int(f.amount_minor), f.confidence, source)

    def day(self, name: str, f: Day | None, source: str) -> Untrusted[date] | None:
        if f is None or not f.value:
            return None
        return self.day_value(name, f.value, f.confidence, source)

    def day_value(self, name: str, raw: str | None, confidence: float, source: str) -> Untrusted[date] | None:
        if not raw:
            return None
        try:
            d = date.fromisoformat(raw.strip())
        except ValueError:
            self.invalid.append(name)
            return None
        return self._wrap(name, d, confidence, source)

    def ref(self, name: str, f: Text | None, source: str) -> Untrusted[str] | None:
        if f is None or not f.value:
            return None
        v = f.value.strip().upper()
        if not REF_PATTERN.match(v):
            self.invalid.append(name)
            return None
        return self._wrap(name, v, f.confidence, source)

    def account(self, f: Text | None, source: str) -> tuple[Untrusted[str] | None, str | None]:
        if f is None or not f.value:
            return None, None
        compact = normalize(PiiKind.ACCOUNT, f.value)
        if not ACCOUNT_PATTERN.match(compact) or not any(c.isdigit() for c in compact):
            self.invalid.append("payee_account")
            return None, None
        if self.tok is None:
            return None, compact[-4:]
        return self._wrap("payee_account", self.tok.token(PiiKind.ACCOUNT, compact), f.confidence, source), compact[-4:]


def _currency(*values: str | None) -> str | None:
    for v in values:
        if v and CURRENCY_PATTERN.match(v.strip().upper()):
            return v.strip().upper()
    return None


def _clip(s: str | None, n: int = 80) -> str | None:
    return s.strip()[:n] if s and s.strip() else None


def build_fields(email_id: str, extractions: list[Extraction],
                 tokenizer: Tokenizer | None) -> tuple[DocumentFields, OwnerView]:
    """Merge the email-body extraction with its documents. A document's own values (invoice number, total, due
    date, remit-to account) win over what the body says; the body's amount is kept separately for comparison."""
    b = _Builder(tokenizer)
    out: dict = {"extraction_status": {x.source: x.status for x in extractions}}
    owner = OwnerView()
    email = next((x.data for x in extractions if isinstance(x.data, EmailExtraction)), None)
    invoices = [x for x in extractions if isinstance(x.data, InvoiceExtraction)]
    receipts = [x for x in extractions if isinstance(x.data, ReceiptExtraction)]
    signals = [x.data.safety for x in extractions if x.data is not None]
    out["model_instruction_flag"] = any(s.instruction_like_text_detected for s in signals)
    out["model_instruction_category"] = next(
        (s.instruction_like_text_category for s in signals if s.instruction_like_text_category), None)
    out["model_urgency"] = any(s.urgency_language for s in signals)
    out["model_secrecy"] = any(s.secrecy_or_no_callback_request for s in signals)

    src = f"{email_id}:email"
    if email:
        out["category"] = email.email_category
        out["amount_minor"] = b.money("amount", email.amount, src)
        out["due_date"] = b.day("due_date", email.due_date, src)
        out["invoice_number"] = b.ref("invoice_number", email.invoice_number, src)
        refs = []
        for r in email.referenced_invoice_numbers:
            v = r.strip().upper()
            (refs.append(v) if REF_PATTERN.match(v) else b.invalid.append("referenced_invoice_numbers"))
        out["referenced_invoice_numbers"] = tuple(dict.fromkeys(refs))
        out["po_number"] = b.ref("po_number", email.po_number, src)
        out["po_direction"] = email.po_direction
        out["start_date"] = b.day("start_date", email.invoice_or_delivery_date, src)
        if email.payment_terms_days.value is not None:
            out["payment_terms_days"] = b._wrap("payment_terms_days", email.payment_terms_days.value,
                                                email.payment_terms_days.confidence, src)
        out["payee_account_token"], out["payee_account_last4"] = b.account(email.payee_account, src)
        out["asks_to_change_bank_details"] = email.asks_to_change_bank_details
        promises = []
        for p in email.promises:
            d = b.day_value("promises", p.date, p.confidence, src)
            if d is None:
                continue
            amt = b.money("promises", Money(amount_minor=p.amount_minor, confidence=p.confidence), src) \
                if p.amount_minor is not None else None
            promises.append(PromiseField(date=d, amount_minor=amt))
        out["promises"] = tuple(promises)
        out["currency"] = _currency(email.currency)
        owner = owner.model_copy(update={"payee_name": _clip(email.payee_name.value),
                                         "payee_bank_name": _clip(email.payee_bank_name.value)})

    for x in invoices:
        inv: InvoiceExtraction = x.data
        s = f"{email_id}:{x.source}"
        out["has_invoice_document"] = True
        if out.get("amount_minor") is not None:
            out["email_amount_minor"] = out["amount_minor"]
        out["amount_minor"] = b.money("amount", inv.total, s) or out.get("amount_minor")
        if (num := b.ref("invoice_number", inv.invoice_number, s)) is not None:
            out["invoice_number"], out["invoice_number_from_document"] = num, True
        out["due_date"] = b.day("due_date", inv.due_date, s) or out.get("due_date")
        out["start_date"] = b.day("start_date", inv.invoice_date, s) or out.get("start_date")
        token, last4 = b.account(inv.payee_account, s)
        if token is not None or last4 is not None:
            out["payee_account_token"], out["payee_account_last4"] = token, last4
        items = [li.amount_minor for li in inv.line_items if li.amount_minor is not None]
        out["line_items_sum_minor"] = sum(items) if items else None
        out["stated_total_minor"] = inv.total.amount_minor
        out["model_totals_mismatch"] = out.get("model_totals_mismatch", False) or inv.totals_mismatch
        out["marked_overdue"] = inv.marked_overdue_or_reminder
        out["currency"] = out.get("currency") or _currency(inv.currency)
        owner = owner.model_copy(update={
            "supplier_name": _clip(inv.supplier_name.value),
            "payee_bank_name": _clip(inv.payee_bank_name.value) or owner.payee_bank_name,
            "line_items": [(_clip(li.description) or "", li.amount_minor) for li in inv.line_items]})

    for x in receipts:
        rc: ReceiptExtraction = x.data
        s = f"{email_id}:{x.source}"
        out["has_receipt"] = True
        if out.get("amount_minor") is not None:
            out["email_amount_minor"] = out["amount_minor"]
        out["amount_minor"] = b.money("amount", rc.total, s) or out.get("amount_minor")
        items = [li.amount_minor for li in rc.line_items if li.amount_minor is not None]
        out["line_items_sum_minor"] = sum(items) if items else None
        out["stated_total_minor"] = rc.total.amount_minor
        out["cash_tendered_minor"] = rc.cash_tendered.amount_minor
        out["change_minor"] = rc.change_given.amount_minor
        out["model_totals_mismatch"] = out.get("model_totals_mismatch", False) or rc.totals_mismatch
        out["currency"] = out.get("currency") or _currency(rc.currency)
        owner = owner.model_copy(update={
            "merchant_name": _clip(rc.merchant_name.value),
            "line_items": [(_clip(li.description) or "", li.amount_minor) for li in rc.line_items]})

    out["invalid_fields"] = tuple(dict.fromkeys(b.invalid))
    out["review_fields"] = tuple(dict.fromkeys(b.review))
    return DocumentFields(**{k: v for k, v in out.items() if v is not None}), owner
