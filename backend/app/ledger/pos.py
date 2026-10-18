"""Point-of-sale data for product margins: the product list and daily per-product sale lines.

`cost_minor` is the product's supplier unit cost on that day times qty, so margins move when a supplier's prices
creep. Refunds are negative qty. Money is integer minor units.
"""

import csv
from datetime import date
from pathlib import Path

from pydantic import BaseModel, ConfigDict


class Product(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    name: str
    category: str | None = None
    supplier_id: str | None = None
    price_minor: int


class SaleLine(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    date: date
    product_id: str
    qty: int
    revenue_minor: int
    cost_minor: int


def _rows(path: Path) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as f:
        return [{k: (v if v != "" else None) for k, v in r.items()} for r in csv.DictReader(f)]


def load_products_csv(path: Path) -> tuple[Product, ...]:
    return tuple(sorted((Product.model_validate(r) for r in _rows(path)), key=lambda p: p.id))


def load_sale_lines_csv(path: Path) -> tuple[SaleLine, ...]:
    return tuple(sorted((SaleLine.model_validate(r) for r in _rows(path)), key=lambda s: (s.date, s.id)))
