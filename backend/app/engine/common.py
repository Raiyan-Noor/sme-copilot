"""Shared helpers for engine calculators: Fact constructors, display formatting, windows, row classification.

Invariant 4: every value the owner sees is built here as a Fact with the rows it came from. Display strings are
formatted in code at this point; the LLM only ever cites the fact ID.
"""

import re
from collections.abc import Iterable
from datetime import date, timedelta
from typing import Literal

from app.engine.pack_inputs import EnginePack
from app.firewall.fact import Fact
from app.ledger.money import format_minor
from app.ledger.snapshot import LedgerSnapshot, Transaction

Line = Literal["revenue", "cogs", "operating", "owner", "transfer", "opening", "uncategorized"]

CLOCK_SOURCE = "clock:today"  # non-ledger source reference, like the packs' "pack:<id>#..." references


def slug(text: str) -> str:
    """Make any identifier safe inside a fact ID (lowercase, [a-z0-9_.:-], starts with a letter)."""
    s = re.sub(r"[^a-z0-9_.:\-]", "_", text.lower())
    return s if s[:1].isalpha() else f"x{s}"


def _ids(rows: Iterable[str]) -> tuple[str, ...]:
    return tuple(sorted(set(rows)))


def money(fid: str, minor: int, currency: str, by: str, sources: Iterable[str] = (),
          inputs: Iterable[str] = ()) -> Fact:
    return Fact(id=fid, value=int(minor), unit="money", currency=currency, display=format_minor(int(minor), currency),
                source_row_ids=_ids(sources), inputs=tuple(inputs), computed_by=by)


def ratio(fid: str, value: float | None, by: str, sources: Iterable[str] = (), inputs: Iterable[str] = ()) -> Fact:
    v = None if value is None else round(value, 4)
    display = "not available" if v is None else f"{v * 100:.1f}%"
    return Fact(id=fid, value=v, unit="ratio", display=display, source_row_ids=_ids(sources), inputs=tuple(inputs),
                computed_by=by)


def days(fid: str, value: float | None, by: str, sources: Iterable[str] = (), inputs: Iterable[str] = (),
         none_display: str = "not available") -> Fact:
    v = None if value is None else round(value, 1)
    display = none_display if v is None else (f"{v:.0f} days" if v == int(v) else f"{v:.1f} days")
    if v == 1:
        display = "1 day"
    return Fact(id=fid, value=v, unit="days", display=display, source_row_ids=_ids(sources), inputs=tuple(inputs),
                computed_by=by)


def a_date(fid: str, d: date | None, by: str, sources: Iterable[str] = (), inputs: Iterable[str] = (),
           none_display: str = "not available") -> Fact:
    display = none_display if d is None else f"{d.day} {d:%b %Y}"
    return Fact(id=fid, value=d, unit="date", display=display, source_row_ids=_ids(sources), inputs=tuple(inputs),
                computed_by=by)


def count(fid: str, n: int, by: str, sources: Iterable[str] = (), inputs: Iterable[str] = ()) -> Fact:
    return Fact(id=fid, value=int(n), unit="count", display=f"{n:,}", source_row_ids=_ids(sources),
                inputs=tuple(inputs), computed_by=by)


def line_of(t: Transaction, pack: EnginePack) -> Line:
    """P&L line for a categorized transaction. Categories the pack does not define are 'uncategorized' and are
    kept out of revenue and costs (an unknown inflow such as a loan must not inflate revenue)."""
    if t.category is None or t.category not in pack.categories:
        return "uncategorized"
    return pack.kind_of(t.category, t.amount_minor)


def window(today: date, n_days: int) -> tuple[date, date]:
    """The last n complete days before today: [today - n, today - 1], inclusive."""
    return today - timedelta(days=n_days), today - timedelta(days=1)


def in_window(snapshot: LedgerSnapshot, start: date, end: date) -> list[Transaction]:
    return [t for t in snapshot.transactions if start <= t.posted_on <= end]


def today_fact(today: date, by: str) -> Fact:
    return a_date("clock.today", today, by, sources=[CLOCK_SOURCE])
