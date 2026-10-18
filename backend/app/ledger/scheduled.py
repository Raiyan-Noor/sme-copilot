"""Known future (or overdue) payables and receivables: rent, payroll, subscriptions, issued customer invoices.

The forecast adds these on their due dates instead of guessing them from history. Amounts are unsigned integer
minor units; `kind` gives the direction. Rows come from the seed's scheduled_items.csv now, and later from the
mailbox extractor (due dates, POs, promises to pay).
"""

import csv
import sqlite3
from datetime import date
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ScheduledItem(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    kind: Literal["payable", "receivable"]
    category: str
    due_date: date
    amount_minor: int = Field(gt=0)
    status: Literal["open", "paid"] = "open"
    counterparty_id: str | None = None
    reference: str | None = None
    source: str | None = None  # contract | invoice | estimate | mailbox ...

    @property
    def signed_minor(self) -> int:
        return self.amount_minor if self.kind == "receivable" else -self.amount_minor


def load_scheduled(conn: sqlite3.Connection) -> tuple[ScheduledItem, ...]:
    """All scheduled items from a tenant DB, sorted by (due_date, id)."""
    rows = conn.execute("SELECT * FROM scheduled_items ORDER BY due_date, id").fetchall()
    return tuple(ScheduledItem.model_validate(dict(r)) for r in rows)


def load_scheduled_csv(path: Path) -> tuple[ScheduledItem, ...]:
    """Read scheduled_items.csv, sorted by (due_date, id) for deterministic engine output."""
    with path.open(encoding="utf-8", newline="") as f:
        rows = [{k: (v if v != "" else None) for k, v in r.items()} for r in csv.DictReader(f)]
    items = [ScheduledItem.model_validate(r) for r in rows]
    return tuple(sorted(items, key=lambda s: (s.due_date, s.id)))
