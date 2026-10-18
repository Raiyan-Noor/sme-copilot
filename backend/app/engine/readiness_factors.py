"""The five raw Readiness Passport factors as Facts (invariant 4). Pure: inputs in, list[Fact] out.

- `passport.raw.inflow_regularity`: share of the last 90 complete days with at least one sales inflow.
- `passport.raw.revenue_stability`: 1 - coefficient of variation of weekly sales over the last 12 complete weeks,
  floored at 0. Steady weeks score near 1; a festival spike lowers it a little, an erratic business a lot.
- `passport.raw.buffer_days`: the cash buffer (`cash.buffer_days`); no recent spending counts as zero, so a
  dormant account never looks strong.
- `passport.raw.collection_days`: average days from issuing a customer invoice to being paid, over invoices issued
  in the last 180 days. An open invoice already past its due date counts at its age today (a lower bound), so
  overdue customers drag the number up instead of vanishing. No customer invoices: zero (sales are paid on the spot).
- `passport.raw.payment_punctuality`: share of supplier invoices due in the last 180 days that were paid on or
  before the due date. Unpaid past the due date counts as late. None due: 100%.

`packs.readiness.readiness_score` then scores these with the active pack's weights and ranges.
"""

import statistics
from datetime import date, timedelta

from app.clock import Clock
from app.engine.common import CLOCK_SOURCE, days, in_window, ratio, window
from app.firewall.fact import Fact
from app.ledger.documents import Receivable, SupplierInvoice
from app.ledger.snapshot import LedgerSnapshot, Transaction
from app.packs.schema import Pack

BY = "engine.readiness_factors"
REGULARITY_DAYS = 90
STABILITY_WEEKS = 12
DOCUMENT_WINDOW_DAYS = 180


def is_revenue(t: Transaction, pack: Pack) -> bool:
    spec = pack.categories.get(t.category or "")
    return spec is not None and spec.kind == "revenue"


def payment_rows(snapshot: LedgerSnapshot) -> dict[str, str]:
    """Statement reference -> ledger row ID, so an invoice's payment can be cited as the row that settled it."""
    return {t.reference: t.id for t in snapshot.transactions if t.reference}


def inflow_regularity(snapshot: LedgerSnapshot, pack: Pack, clock: Clock) -> Fact:
    start, end = window(clock.today(), REGULARITY_DAYS)
    rows = [t for t in in_window(snapshot, start, end) if is_revenue(t, pack) and t.amount_minor > 0]
    active = {t.posted_on for t in rows}
    return ratio("passport.raw.inflow_regularity", len(active) / REGULARITY_DAYS, BY,
                 [t.id for t in rows] or [CLOCK_SOURCE])


def revenue_stability(snapshot: LedgerSnapshot, pack: Pack, clock: Clock) -> Fact:
    start, end = window(clock.today(), STABILITY_WEEKS * 7)
    rows = [t for t in in_window(snapshot, start, end) if is_revenue(t, pack)]
    weeks = [0] * STABILITY_WEEKS
    for t in rows:
        weeks[(t.posted_on - start).days // 7] += t.amount_minor
    mean = statistics.fmean(weeks)
    value = 0.0 if mean <= 0 else max(0.0, 1.0 - statistics.pstdev(weeks) / mean)
    return ratio("passport.raw.revenue_stability", value, BY, [t.id for t in rows] or [CLOCK_SOURCE])


def buffer_factor(buffer: Fact) -> Fact:
    value = buffer.value if isinstance(buffer.value, int | float) else 0.0
    return days("passport.raw.buffer_days", float(value), BY, inputs=[buffer.id])


def collection_days(receivables: tuple[Receivable, ...], snapshot: LedgerSnapshot, clock: Clock) -> Fact:
    today = clock.today()
    since = today - timedelta(days=DOCUMENT_WINDOW_DAYS)
    paid_by = payment_rows(snapshot)
    ages: list[int] = []
    sources: list[str] = []
    for r in receivables:
        if not since <= r.issue_date < today:
            continue
        if r.paid_on is not None and r.paid_on <= today:
            ages.append((r.paid_on - r.issue_date).days)
        elif r.due_date < today:
            ages.append((today - r.issue_date).days)
        else:
            continue  # not yet due: nothing to say about it
        sources.append(r.id)
        if r.payment_reference in paid_by:
            sources.append(paid_by[r.payment_reference])
    if not ages:
        return Fact(id="passport.raw.collection_days", value=0.0, unit="days", display="no customer invoices",
                    source_row_ids=(CLOCK_SOURCE,), computed_by=BY)
    return days("passport.raw.collection_days", statistics.fmean(ages), BY, sources)


def payment_punctuality(invoices: tuple[SupplierInvoice, ...], snapshot: LedgerSnapshot, clock: Clock) -> Fact:
    today = clock.today()
    since = today - timedelta(days=DOCUMENT_WINDOW_DAYS)
    paid_by = payment_rows(snapshot)
    due = [i for i in invoices if since <= i.due_date < today]
    if not due:
        return Fact(id="passport.raw.payment_punctuality", value=1.0, unit="ratio",
                    display="no supplier invoices due", source_row_ids=(CLOCK_SOURCE,), computed_by=BY)
    on_time = sum(1 for i in due if i.paid_on is not None and i.paid_on <= i.due_date)
    sources = [i.id for i in due] + [paid_by[i.payment_reference] for i in due if i.payment_reference in paid_by]
    return ratio("passport.raw.payment_punctuality", on_time / len(due), BY, sources)


def readiness_raw_facts(snapshot: LedgerSnapshot, pack: Pack, clock: Clock, buffer: Fact,
                        receivables: tuple[Receivable, ...] = (),
                        supplier_invoices: tuple[SupplierInvoice, ...] = ()) -> dict[str, Fact]:
    """Raw factor Facts keyed by readiness factor name (the keys `packs.readiness.readiness_score` expects)."""
    return {
        "inflow_regularity": inflow_regularity(snapshot, pack, clock),
        "revenue_stability": revenue_stability(snapshot, pack, clock),
        "buffer_days": buffer_factor(buffer),
        "collection_days": collection_days(receivables, snapshot, clock),
        "payment_punctuality": payment_punctuality(supplier_invoices, snapshot, clock),
    }


def months_between(start: date, end: date) -> int:
    """Whole calendar months from `start` to `end` (0 if end is before start)."""
    n = (end.year - start.year) * 12 + end.month - start.month - (1 if end.day < start.day else 0)
    return max(0, n)


def add_months(d: date, n: int) -> date:
    y, m = divmod(d.month - 1 + n, 12)
    year, month = d.year + y, m + 1
    for day in (d.day, 30, 29, 28):
        try:
            return date(year, month, day)
        except ValueError:
            continue
    raise ValueError("unreachable")
