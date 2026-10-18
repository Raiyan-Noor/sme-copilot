"""Structured Outputs schemas for the quarantined extractor: one per document kind (email, invoice, receipt).

These are what the extractor model must return (bound as a strict json_schema; the adapter validates the reply
against the same model). They are deliberately loose about formats (plain strings with length caps): a malformed
identifier is dropped field by field in typed.py rather than discarding the whole document. Nothing here reaches
the planner; typed.py turns it into validated, provenance-tagged fields first (invariants 2 and 3).

There is no free-text summary field anywhere, so the extractor cannot restate an instruction it was shown.
Names and line-item descriptions exist only for the owner's screen.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

EmailCategory = Literal[
    "invoice", "payment_request", "bank_detail_change", "purchase_order", "payment_confirmation", "promise_to_pay",
    "overdue_notice", "loan_offer", "other_financial", "not_financial",
]
InstructionCategory = Literal[
    "ignore_instructions", "claims_owner_authority", "payment_or_approval_request", "data_exfiltration",
    "mandate_or_policy_change", "concealment", "other",
]
PoDirection = Literal["incoming_from_customer", "outgoing_to_supplier", "supplier_confirmation"]

Conf = Field(ge=0, le=1)


class _Out(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Text(_Out):
    value: str | None = Field(max_length=120)
    confidence: float = Conf


class Money(_Out):
    amount_minor: int | None = Field(ge=0, le=10**13)
    confidence: float = Conf


class Day(_Out):
    value: str | None = Field(max_length=10, description="YYYY-MM-DD")
    confidence: float = Conf


class Count(_Out):
    value: int | None = Field(ge=0, le=3650)
    confidence: float = Conf


class Promise(_Out):
    date: str | None = Field(max_length=10, description="YYYY-MM-DD")
    amount_minor: int | None = Field(ge=0, le=10**13)
    confidence: float = Conf


class SafetySignals(_Out):
    instruction_like_text_detected: bool
    instruction_like_text_category: InstructionCategory | None
    urgency_language: bool
    secrecy_or_no_callback_request: bool


class EmailExtraction(_Out):
    """The email body (headers are parsed in code, not here)."""

    email_category: EmailCategory
    currency: str | None = Field(max_length=3)
    amount: Money
    due_date: Day
    invoice_number: Text
    referenced_invoice_numbers: list[str] = Field(max_length=10)
    po_number: Text
    po_direction: PoDirection | None
    invoice_or_delivery_date: Day
    payment_terms_days: Count
    payee_name: Text
    payee_bank_name: Text
    payee_account: Text
    asks_to_change_bank_details: bool
    promises: list[Promise] = Field(max_length=6)
    safety: SafetySignals


class LineItem(_Out):
    description: str | None = Field(max_length=80)
    amount_minor: int | None = Field(ge=0, le=10**12)


class InvoiceExtraction(_Out):
    """An invoice document (PDF attachment text)."""

    doc_type: Literal["invoice", "credit_note", "statement", "other"]
    supplier_name: Text
    supplier_email: Text
    invoice_number: Text
    invoice_date: Day
    due_date: Day
    currency: str | None = Field(max_length=3)
    line_items: list[LineItem] = Field(max_length=60)
    total: Money
    totals_mismatch: bool
    payee_bank_name: Text
    payee_account: Text
    marked_overdue_or_reminder: bool
    safety: SafetySignals


class ReceiptExtraction(_Out):
    """A receipt photo or scan (vision)."""

    merchant_name: Text
    receipt_date: Day
    currency: str | None = Field(max_length=3)
    line_items: list[LineItem] = Field(max_length=60)
    subtotal: Money
    total: Money
    cash_tendered: Money
    change_given: Money
    totals_mismatch: bool
    safety: SafetySignals


DocKind = Literal["email", "invoice", "receipt"]
SCHEMAS: dict[str, type[_Out]] = {"email": EmailExtraction, "invoice": InvoiceExtraction, "receipt": ReceiptExtraction}
