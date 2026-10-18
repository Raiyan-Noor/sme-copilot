"""Profit and loss by period (cash basis) and gross margin. Pure: (snapshot, pack, clock) -> list[Fact].

Cash basis: revenue is money received in revenue categories, cost of goods is supplier payments (cogs categories),
operating expenses are operating categories. Owner drawings, transfers between own accounts and opening balances
are not P&L. Rows in categories the pack does not define are reported separately as uncategorized. Only days
before today count, so a period in progress shows what has happened so far (`days_covered` says how much).
"""

from collections import defaultdict
from datetime import date
from typing import Literal

from app.clock import Clock
from app.engine.common import a_date, count, in_window, line_of, money, ratio, slug, window
from app.engine.pack_inputs import EnginePack
from app.firewall.fact import Fact
from app.ledger.snapshot import LedgerSnapshot, Transaction

Period = Literal["month", "week"]
BY_PNL = "engine.pnl.pnl_by_period"
BY_MARGIN = "engine.pnl.gross_margin"


def period_key(d: date, period: Period) -> str:
    if period == "month":
        return f"{d:%Y-%m}"
    iso = d.isocalendar()
    return f"{iso.year}-w{iso.week:02d}"


def _lines(rows: list[Transaction], pack: EnginePack, currency: str, prefix: str, by: str) -> list[Fact]:
    """Revenue, COGS, gross profit and margin, opex by category, operating profit, owner drawings, uncategorized."""
    by_line: dict[str, list[Transaction]] = defaultdict(list)
    for t in rows:
        by_line[line_of(t, pack)].append(t)

    def total(ts: list[Transaction]) -> int:
        return sum(t.amount_minor for t in ts)

    def ids(ts: list[Transaction]) -> list[str]:
        # A zero line cites every row it scanned, so "nothing here" is still traceable.
        return [t.id for t in ts] or [t.id for t in rows]

    rev, cogs, opex = by_line["revenue"], by_line["cogs"], by_line["operating"]
    revenue, cost = total(rev), -total(cogs)
    operating = -total(opex)
    gross = revenue - cost
    f = [
        money(f"{prefix}.revenue", revenue, currency, by, ids(rev)),
        money(f"{prefix}.cogs", cost, currency, by, ids(cogs)),
        money(f"{prefix}.gross_profit", gross, currency, by, ids(rev + cogs),
              inputs=[f"{prefix}.revenue", f"{prefix}.cogs"]),
        ratio(f"{prefix}.gross_margin", gross / revenue if revenue else None, by, ids(rev + cogs),
              inputs=[f"{prefix}.revenue", f"{prefix}.gross_profit"]),
        money(f"{prefix}.operating_expenses", operating, currency, by, ids(opex)),
        money(f"{prefix}.operating_profit", gross - operating, currency, by, ids(rev + cogs + opex),
              inputs=[f"{prefix}.gross_profit", f"{prefix}.operating_expenses"]),
    ]
    by_cat: dict[tuple[str, str], list[Transaction]] = defaultdict(list)
    for t in rev + opex:
        by_cat[(line_of(t, pack), t.category or "")].append(t)
    for (line, cat), ts in sorted(by_cat.items()):
        sign = 1 if line == "revenue" else -1
        part = "revenue" if line == "revenue" else "expense"
        f.append(money(f"{prefix}.{part}.{slug(cat)}", sign * total(ts), currency, by, ids(ts)))
    if by_line["owner"]:
        f.append(money(f"{prefix}.owner_drawings", -total(by_line["owner"]), currency, by, ids(by_line["owner"])))
    unc = by_line["uncategorized"]
    if unc:
        unc_in = [t for t in unc if t.amount_minor > 0]
        unc_out = [t for t in unc if t.amount_minor < 0]
        f.append(count(f"{prefix}.uncategorized.count", len(unc), by, ids(unc)))
        if unc_in:
            f.append(money(f"{prefix}.uncategorized.inflows", total(unc_in), currency, by, ids(unc_in)))
        if unc_out:
            f.append(money(f"{prefix}.uncategorized.outflows", -total(unc_out), currency, by, ids(unc_out)))
    return f


def pnl_by_period(snapshot: LedgerSnapshot, pack: EnginePack, clock: Clock, period: Period = "month") -> list[Fact]:
    """One block of P&L facts per calendar month (or ISO week), IDs like `pnl.2026-09.revenue`."""
    today = clock.today()
    history = [t for t in snapshot.transactions if t.posted_on < today]
    groups: dict[str, list[Transaction]] = defaultdict(list)
    for t in history:
        groups[period_key(t.posted_on, period)].append(t)
    facts: list[Fact] = []
    for key in sorted(groups):
        rows = groups[key]
        prefix = f"pnl.{key}"
        first, last = min(t.posted_on for t in rows), max(t.posted_on for t in rows)
        first_ids = [t.id for t in rows if t.posted_on == first]
        last_ids = [t.id for t in rows if t.posted_on == last]
        facts += [
            a_date(f"{prefix}.first_day", first, BY_PNL, first_ids),
            a_date(f"{prefix}.last_day", last, BY_PNL, last_ids),
            count(f"{prefix}.days_covered", (last - first).days + 1, BY_PNL, first_ids + last_ids),
        ]
        facts += _lines(rows, pack, snapshot.currency, prefix, BY_PNL)
    return facts


def gross_margin(snapshot: LedgerSnapshot, pack: EnginePack, clock: Clock, window_days: int = 90) -> list[Fact]:
    """Revenue, COGS, gross profit and gross margin over the last `window_days` complete days."""
    start, end = window(clock.today(), window_days)
    rows = in_window(snapshot, start, end)
    prefix = f"margin.last_{window_days}d"
    keep = {"revenue", "cogs", "gross_profit", "gross_margin"}
    facts = [f for f in _lines(rows, pack, snapshot.currency, prefix, BY_MARGIN) if f.id.rsplit(".", 1)[1] in keep]
    by_id = {f.id: f for f in facts}
    trace = by_id[f"{prefix}.revenue"].source_row_ids + by_id[f"{prefix}.cogs"].source_row_ids
    return [
        a_date(f"{prefix}.start", start, BY_MARGIN, trace or ["clock:today"]),
        a_date(f"{prefix}.end", end, BY_MARGIN, trace or ["clock:today"]),
        *facts,
    ]
