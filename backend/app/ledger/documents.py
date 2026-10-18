"""Invoice documents from the business's own records: customer invoices it issued (receivables.csv) and supplier
invoices it received (grouped here per invoice from the purchase lines in ledger.purchases).

The Readiness Passport reads them for collection days (issue -> paid) and payment punctuality (paid by the due
date). They come from the business's bookkeeping export, like the point-of-sale files, never from the mailbox:
mailbox invoices are untrusted and go through the quarantined extractor (invariant 2). Money is integer minor
units. `payment_reference` is the statement reference of the ledger row that settled the invoice.
"""

import csv
from collections import defaultdict
from collections.abc import Iterable
from datetime import date
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from app.ledger.purchases import PurchaseLine


class Receivable(BaseModel):
    """A customer invoice the business issued."""

    model_config = ConfigDict(frozen=True)

    id: str
    customer_id: str
    issue_date: date
    due_date: date
    amount_minor: int = Field(gt=0)
    status: str
    paid_on: date | None = None
    payment_reference: str | None = None


class SupplierInvoice(BaseModel):
    """A supplier invoice the business received; `amount_minor` is the sum of its lines."""

    model_config = ConfigDict(frozen=True)

    id: str
    supplier_id: str
    invoice_date: date
    due_date: date
    amount_minor: int = Field(gt=0)
    paid_on: date | None = None
    payment_reference: str | None = None


def _rows(path: Path) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as f:
        return [{k: (v if v != "" else None) for k, v in r.items()} for r in csv.DictReader(f)]


def load_receivables_csv(path: Path) -> tuple[Receivable, ...]:
    return tuple(sorted((Receivable.model_validate(r) for r in _rows(path)), key=lambda r: (r.issue_date, r.id)))


def supplier_invoices(lines: Iterable[PurchaseLine]) -> tuple[SupplierInvoice, ...]:
    """Group purchase lines (ledger.purchases) by invoice. Every line of an invoice shares its dates and payment."""
    grouped: dict[str, list[PurchaseLine]] = defaultdict(list)
    for line in lines:
        grouped[line.invoice_id].append(line)
    out = []
    for invoice_id, rows in grouped.items():
        first = rows[0]
        out.append(SupplierInvoice(
            id=invoice_id, supplier_id=first.supplier_id, invoice_date=first.invoice_date, due_date=first.due_date,
            amount_minor=max(1, sum(r.line_total_minor for r in rows)), paid_on=first.paid_on,
            payment_reference=first.payment_reference))
    return tuple(sorted(out, key=lambda i: (i.invoice_date, i.id)))
