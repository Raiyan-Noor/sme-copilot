"""Supplier purchase lines: one row per product line on a supplier invoice (purchases.csv).

Leak detectors read these for unit costs (price creep), early-pay discount terms (missed discounts) and units
bought (slow-moving stock). Money is integer minor units; `early_pay_discount_pct` is a ratio (0.02 = 2%).
Rows come from the business's own purchasing records, not from untrusted documents: an invoice read from an email
by the extractor never lands here.
"""

import csv
from datetime import date
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field


class PurchaseLine(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    invoice_id: str
    supplier_id: str
    invoice_date: date
    due_date: date
    product_id: str
    qty: int = Field(gt=0)
    unit_cost_minor: int = Field(ge=0)
    line_total_minor: int = Field(ge=0)
    paid_on: date | None = None
    payment_reference: str | None = None
    early_pay_discount_pct: float = Field(default=0.0, ge=0, le=1)
    discount_deadline: date | None = None


def load_purchases_csv(path: Path) -> tuple[PurchaseLine, ...]:
    """Read purchases.csv, sorted by (invoice_date, id) for deterministic detector output."""
    with path.open(encoding="utf-8", newline="") as f:
        rows = [{k: (v if v != "" else None) for k, v in r.items()} for r in csv.DictReader(f)]
    lines = [PurchaseLine.model_validate({**r, "early_pay_discount_pct": r.get("early_pay_discount_pct") or 0})
             for r in rows]
    return tuple(sorted(lines, key=lambda p: (p.invoice_date, p.id)))
