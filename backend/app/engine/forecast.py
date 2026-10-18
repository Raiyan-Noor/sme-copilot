"""30/60/90-day cash forecast and runway. Pure: (snapshot, pack, clock, scheduled items) -> list[Fact].

Model, per future day d (day 1 is today, before any of today's rows have posted):

    flow(d) = seasonality(d) * (baseline_in[weekday(d)] - baseline_out[weekday(d)]) + scheduled(d)

- Baseline: for each weekday, the mean deseasonalized inflow and outflow over the last LOOKBACK_DAYS complete days,
  using rows in categories the pack does NOT mark `scheduled` (sales, supplier payments, fees, uncategorized
  outflows). Each history day is divided by its own seasonality multiplier first, so a past holiday spike does not
  inflate the baseline.
- Seasonality: the pack's month multiplier times the holiday multiplier of any calendar window covering the day.
- Scheduled: open ScheduledItems in categories the pack marks `scheduled` (rent, payroll, customer dues...),
  added on their due date. Items in baseline categories (e.g. an open supplier invoice) are already represented by
  the baseline and are not added again; they are counted in `forecast.scheduled.in_baseline.count`. Items in
  a category the pack does not define at all are not added either and are counted in
  `forecast.scheduled.unmatched.count`, so a category mismatch is visible instead of silent.
  Overdue payables are assumed paid today. Overdue receivables are left out of the expected path.
- Promises to pay: a customer's promise read from a clean inbox email (quarantine/feed.py, source
  `mailbox_promise`) is a receivable on the promised date. The invoice it refers to (same reference) is superseded
  for the projection, so its cash is counted once, on the promised date. Superseded invoices are counted in
  `forecast.scheduled.superseded_by_promise.count`.

Uncertainty band (about 80%): sigma is the standard deviation of daily baseline residuals (actual minus model)
over the lookback; after h days the band is Z * sigma * sqrt(h). The low path also drops every receivable not yet
collected; the high path also collects every overdue receivable today. Not a confidence interval in any formal
sense; a simple, explainable spread.
"""

import math
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta

from app.clock import Clock
from app.engine.cash import cash_balance
from app.engine.common import a_date, count, days, line_of, money, window
from app.engine.pack_inputs import EnginePack
from app.firewall.fact import Fact
from app.ledger.scheduled import ScheduledItem
from app.ledger.snapshot import LedgerSnapshot

BY = "engine.forecast.forecast"
BY_RUNWAY = "engine.forecast.runway"
HORIZONS = (30, 60, 90)
LOOKBACK_DAYS = 56  # eight of each weekday
Z = 1.2816  # two-sided 80%
WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
BASELINE_LINES = frozenset({"revenue", "cogs", "operating", "uncategorized"})
PROMISE_SOURCE = "mailbox_promise"  # quarantine/feed.py


@dataclass(frozen=True)
class _Day:
    day: date
    multiplier: float
    baseline_in: int
    baseline_out: int
    scheduled_in: int
    scheduled_out: int
    scheduled_ids: tuple[str, ...]
    expected: int
    low: int
    high: int


@dataclass(frozen=True)
class _Projection:
    start_balance: Fact
    baseline_facts: list[Fact]
    sigma: Fact
    overdue_receivables: list[ScheduledItem]
    in_baseline: list[ScheduledItem]
    unmatched: list[ScheduledItem]
    superseded: list[ScheduledItem]
    days: list[_Day]
    baseline_row_ids: tuple[str, ...]


def _baseline(snapshot: LedgerSnapshot, pack: EnginePack, today: date):
    """Per-weekday mean deseasonalized inflow and outflow, the residual sigma, and the rows used."""
    start, end = window(today, LOOKBACK_DAYS)
    daily_in: dict[date, int] = defaultdict(int)
    daily_out: dict[date, int] = defaultdict(int)
    rows_by_wd: dict[int, list[str]] = defaultdict(list)
    for t in snapshot.transactions:
        if not (start <= t.posted_on <= end) or line_of(t, pack) not in BASELINE_LINES:
            continue
        if t.category is not None and pack.is_scheduled(t.category):
            continue
        if line_of(t, pack) == "uncategorized" and t.amount_minor > 0:
            continue  # an unknown inflow (a loan, a refund) is not a repeating sale
        if t.amount_minor >= 0:
            daily_in[t.posted_on] += t.amount_minor
        else:
            daily_out[t.posted_on] += -t.amount_minor
        rows_by_wd[t.posted_on.weekday()].append(t.id)

    history = [start + timedelta(days=i) for i in range(LOOKBACK_DAYS)]
    mean_in, mean_out = [0.0] * 7, [0.0] * 7
    for wd in range(7):
        ds = [d for d in history if d.weekday() == wd]
        mean_in[wd] = sum(daily_in[d] / pack.multiplier(d) for d in ds) / len(ds)
        mean_out[wd] = sum(daily_out[d] / pack.multiplier(d) for d in ds) / len(ds)
    residuals = [
        (daily_in[d] - daily_out[d]) - pack.multiplier(d) * (mean_in[d.weekday()] - mean_out[d.weekday()])
        for d in history
    ]
    mu = sum(residuals) / len(residuals)
    sigma = math.sqrt(sum((r - mu) ** 2 for r in residuals) / len(residuals))
    return mean_in, mean_out, sigma, rows_by_wd


def _project(snapshot: LedgerSnapshot, pack: EnginePack, clock: Clock,
             scheduled: tuple[ScheduledItem, ...]) -> _Projection:
    today = clock.today()
    cur = snapshot.currency
    start_balance = cash_balance(snapshot, clock)[0]
    mean_in, mean_out, sigma, rows_by_wd = _baseline(snapshot, pack, today)

    baseline_facts: list[Fact] = []
    for wd, name in enumerate(WEEKDAYS):
        src = rows_by_wd.get(wd) or ["clock:today"]
        baseline_facts += [
            money(f"forecast.baseline.{name}.inflow", round(mean_in[wd]), cur, BY, src),
            money(f"forecast.baseline.{name}.outflow", round(mean_out[wd]), cur, BY, src),
        ]
    all_baseline_ids = tuple(sorted({i for ids in rows_by_wd.values() for i in ids}))
    sigma_fact = money("forecast.band.daily_sigma", round(sigma), cur, BY, all_baseline_ids or ["clock:today"])

    open_items = [s for s in scheduled if s.status == "open"]
    promised = {s.reference for s in open_items if s.source == PROMISE_SOURCE and s.reference}
    superseded = [s for s in open_items if s.source != PROMISE_SOURCE and s.kind == "receivable"
                  and s.reference in promised]
    open_items = [s for s in open_items if s not in superseded]
    counted = [s for s in open_items if pack.is_scheduled(s.category)]
    in_baseline = [s for s in open_items if s.category in pack.categories and not pack.is_scheduled(s.category)]
    unmatched = [s for s in open_items if s.category not in pack.categories]
    overdue_rec = [s for s in counted if s.kind == "receivable" and s.due_date < today]
    due: dict[date, list[ScheduledItem]] = defaultdict(list)
    for s in counted:
        if s.kind == "payable":
            due[max(s.due_date, today)].append(s)  # overdue payables: assume paid today
        elif s.due_date >= today:
            due[s.due_date].append(s)

    overdue_total = sum(s.amount_minor for s in overdue_rec)
    balance = start_balance.value
    future_rec = 0
    out: list[_Day] = []
    for h in range(1, HORIZONS[-1] + 1):
        d = today + timedelta(days=h - 1)
        m = pack.multiplier(d)
        b_in, b_out = round(m * mean_in[d.weekday()]), round(m * mean_out[d.weekday()])
        items = due.get(d, [])
        s_in = sum(s.amount_minor for s in items if s.kind == "receivable")
        s_out = sum(s.amount_minor for s in items if s.kind == "payable")
        future_rec += s_in
        balance += b_in - b_out + s_in - s_out
        band = round(Z * sigma * math.sqrt(h))
        out.append(_Day(d, m, b_in, b_out, s_in, s_out, tuple(s.id for s in items), balance,
                        balance - band - future_rec, balance + band + overdue_total))
    return _Projection(start_balance, baseline_facts, sigma_fact, overdue_rec, in_baseline, unmatched, superseded,
                       out, all_baseline_ids)


def forecast(snapshot: LedgerSnapshot, pack: EnginePack, clock: Clock,
             scheduled: tuple[ScheduledItem, ...] = ()) -> list[Fact]:
    """Summary facts per horizon (`forecast.30d.end_balance`, `.low`, `.high`, `.inflows`, `.outflows`,
    `.scheduled_in`, `.scheduled_out`, `.min_balance`, `.min_balance_date`, `.end_date`) and one daily
    expected/low/high balance fact per day for the chart (`forecast.daily.2026-10-19.expected`)."""
    p = _project(snapshot, pack, clock, scheduled)
    cur = snapshot.currency
    model_inputs = ["cash.balance", p.sigma.id, *(f.id for f in p.baseline_facts)]
    facts: list[Fact] = [p.start_balance, *p.baseline_facts, p.sigma]

    overdue_ids = [s.id for s in p.overdue_receivables]
    if overdue_ids:
        facts += [money("forecast.overdue_receivables", sum(s.amount_minor for s in p.overdue_receivables), cur, BY,
                        overdue_ids),
                  count("forecast.overdue_receivables.count", len(overdue_ids), BY, overdue_ids)]
    if p.in_baseline:
        facts.append(count("forecast.scheduled.in_baseline.count", len(p.in_baseline), BY,
                           [s.id for s in p.in_baseline]))
    if p.unmatched:
        facts.append(count("forecast.scheduled.unmatched.count", len(p.unmatched), BY, [s.id for s in p.unmatched]))
    if p.superseded:
        facts.append(count("forecast.scheduled.superseded_by_promise.count", len(p.superseded), BY,
                           [s.id for s in p.superseded]))

    for n in HORIZONS:
        span = p.days[:n]
        sched_ids = [i for d in span for i in d.scheduled_ids]
        pre = f"forecast.{n}d"
        inflows = sum(d.baseline_in + d.scheduled_in for d in span)
        outflows = sum(d.baseline_out + d.scheduled_out for d in span)
        low_day = min(span, key=lambda d: (d.expected, d.day))
        trace = sched_ids or list(p.baseline_row_ids) or ["clock:today"]
        facts += [
            a_date(f"{pre}.end_date", span[-1].day, BY, ["clock:today"]),
            money(f"{pre}.end_balance", span[-1].expected, cur, BY, sched_ids, inputs=model_inputs),
            money(f"{pre}.end_balance_low", span[-1].low, cur, BY, sched_ids + overdue_ids, inputs=model_inputs),
            money(f"{pre}.end_balance_high", span[-1].high, cur, BY, sched_ids + overdue_ids, inputs=model_inputs),
            money(f"{pre}.inflows", inflows, cur, BY, sched_ids, inputs=model_inputs[2:]),
            money(f"{pre}.outflows", outflows, cur, BY, sched_ids, inputs=model_inputs[2:]),
            money(f"{pre}.scheduled_in", sum(d.scheduled_in for d in span), cur, BY, trace),
            money(f"{pre}.scheduled_out", sum(d.scheduled_out for d in span), cur, BY, trace),
            money(f"{pre}.min_balance", low_day.expected, cur, BY, sched_ids, inputs=model_inputs),
            a_date(f"{pre}.min_balance_date", low_day.day, BY, sched_ids, inputs=[f"{pre}.min_balance"]),
        ]

    for d in p.days:
        upto = [i for x in p.days if x.day <= d.day for i in x.scheduled_ids]
        key = f"forecast.daily.{d.day.isoformat()}"
        facts += [
            money(f"{key}.expected", d.expected, cur, BY, upto, inputs=model_inputs),
            money(f"{key}.low", d.low, cur, BY, upto + overdue_ids, inputs=model_inputs),
            money(f"{key}.high", d.high, cur, BY, upto + overdue_ids, inputs=model_inputs),
        ]
    return facts


def runway(snapshot: LedgerSnapshot, pack: EnginePack, clock: Clock,
           scheduled: tuple[ScheduledItem, ...] = ()) -> list[Fact]:
    """Days until the forecast balance first goes below zero: `runway.days` / `runway.date` on the expected path,
    `runway.stressed.days` / `runway.stressed.date` on the low path. None (shown in words) if it stays at or above
    zero for the whole horizon."""
    p = _project(snapshot, pack, clock, scheduled)
    horizon = HORIZONS[-1]
    beyond = f"more than {horizon} days"
    facts: list[Fact] = []
    for name, attr in (("runway", "expected"), ("runway.stressed", "low")):
        hit = next((i for i, d in enumerate(p.days) if getattr(d, attr) < 0), None)
        sched = [s for d in p.days[: (hit if hit is not None else horizon) + 1] for s in d.scheduled_ids]
        daily_id = (f"forecast.daily.{p.days[hit].day.isoformat()}.{attr}" if hit is not None
                    else f"forecast.{horizon}d.end_balance")
        inputs = ["cash.balance", daily_id]
        facts += [
            days(f"{name}.days", None if hit is None else hit, BY_RUNWAY, sched, inputs=inputs, none_display=beyond),
            a_date(f"{name}.date", None if hit is None else p.days[hit].day, BY_RUNWAY, sched, inputs=inputs,
                   none_display=beyond),
        ]
    return facts
