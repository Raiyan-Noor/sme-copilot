"""Response models for the finance read routes, shaped from one request's FactStore.

Presentation only: every number is an engine Fact passed through unchanged (invariant 4), so the UI shows
`display` and can open the explain_fact trace for any of them. Nothing here computes a value.
"""

import datetime as dt
import re
from collections import defaultdict
from datetime import date
from typing import Literal

from pydantic import BaseModel

from app.engine.forecast import HORIZONS
from app.firewall.fact import Fact
from app.firewall.store import FactStore
from app.packs.benchmarks import Status
from app.services.finance import Computed

Period = Literal["month", "week"]
_PERIOD_KEY = {"month": re.compile(r"^\d{4}-\d{2}$"), "week": re.compile(r"^\d{4}-w\d{2}$")}
_PERIOD_META = ("first_day", "last_day", "days_covered")


def _opt(store: FactStore, fact_id: str) -> Fact | None:
    return store.get(fact_id) if fact_id in store else None


class FactList(BaseModel):
    as_of: date
    pack_ref: str
    total: int
    facts: list[Fact]


class PnlPeriod(BaseModel):
    """One period. `lines` is keyed by line ID: revenue, cogs, gross_profit, gross_margin, operating_expenses,
    operating_profit, revenue.<category>, expense.<category>, owner_drawings, uncategorized.count ..."""

    period: str
    first_day: Fact
    last_day: Fact
    days_covered: Fact
    lines: dict[str, Fact]


class PnlResponse(BaseModel):
    as_of: date
    pack_ref: str
    period: Period
    periods: list[PnlPeriod]

    @classmethod
    def build(cls, c: Computed, as_of: date, period: Period) -> "PnlResponse":
        groups: dict[str, dict[str, Fact]] = defaultdict(dict)
        for fact in c.store:
            if not fact.id.startswith("pnl."):
                continue
            key, _, line = fact.id[len("pnl."):].partition(".")
            if _PERIOD_KEY[period].match(key):
                groups[key][line] = fact
        periods = []
        for key in sorted(groups):
            g = groups[key]
            periods.append(PnlPeriod(period=key, first_day=g["first_day"], last_day=g["last_day"],
                                     days_covered=g["days_covered"],
                                     lines={k: v for k, v in g.items() if k not in _PERIOD_META}))
        return cls(as_of=as_of, pack_ref=c.inputs.pack.ref, period=period, periods=periods)


class CashPosition(BaseModel):
    as_of: date
    balance: Fact
    accounts: list[Fact]
    last_activity: Fact | None
    avg_daily_spend: Fact | None
    buffer_days: Fact
    runway_days: Fact
    runway_date: Fact
    runway_stressed_days: Fact
    runway_stressed_date: Fact

    @classmethod
    def build(cls, c: Computed, as_of: date) -> "CashPosition":
        s = c.store
        accounts = [f for f in s if f.id.startswith("cash.balance.")]
        avg = next((f for f in s if f.id.startswith("cash.avg_daily_spend.")), None)
        return cls(as_of=as_of, balance=s.get("cash.balance"), accounts=accounts,
                   last_activity=_opt(s, "cash.last_activity"), avg_daily_spend=avg,
                   buffer_days=s.get("cash.buffer_days"), runway_days=s.get("runway.days"),
                   runway_date=s.get("runway.date"), runway_stressed_days=s.get("runway.stressed.days"),
                   runway_stressed_date=s.get("runway.stressed.date"))


class ForecastHorizon(BaseModel):
    days: int
    end_date: Fact
    end_balance: Fact
    end_balance_low: Fact
    end_balance_high: Fact
    inflows: Fact
    outflows: Fact
    scheduled_in: Fact
    scheduled_out: Fact
    min_balance: Fact
    min_balance_date: Fact


class ForecastDay(BaseModel):
    date: dt.date
    expected: Fact
    low: Fact
    high: Fact


class ForecastResponse(BaseModel):
    """30/60/90-day summaries and the daily expected/low/high path for the chart (about an 80% band)."""

    as_of: date
    pack_ref: str
    start_balance: Fact
    horizons: list[ForecastHorizon]
    daily: list[ForecastDay]
    overdue_receivables: Fact | None
    overdue_receivables_count: Fact | None
    unmatched_scheduled_count: Fact | None

    @classmethod
    def build(cls, c: Computed, as_of: date) -> "ForecastResponse":
        s = c.store
        horizons = [ForecastHorizon(days=n, **{name: s.get(f"forecast.{n}d.{name}") for name in (
            "end_date", "end_balance", "end_balance_low", "end_balance_high", "inflows", "outflows",
            "scheduled_in", "scheduled_out", "min_balance", "min_balance_date")}) for n in HORIZONS]
        days = sorted({f.id.split(".")[2] for f in s if f.id.startswith("forecast.daily.")})
        daily = [ForecastDay(date=date.fromisoformat(d), expected=s.get(f"forecast.daily.{d}.expected"),
                             low=s.get(f"forecast.daily.{d}.low"), high=s.get(f"forecast.daily.{d}.high"))
                 for d in days]
        return cls(as_of=as_of, pack_ref=c.inputs.pack.ref, start_balance=s.get("cash.balance"),
                   horizons=horizons, daily=daily,
                   overdue_receivables=_opt(s, "forecast.overdue_receivables"),
                   overdue_receivables_count=_opt(s, "forecast.overdue_receivables.count"),
                   unmatched_scheduled_count=_opt(s, "forecast.scheduled.unmatched.count"))


class KpiRow(BaseModel):
    kpi_id: str
    label: str
    status: Status
    value: Fact | None
    healthy_min: Fact | None
    healthy_max: Fact | None


class KpiResponse(BaseModel):
    """The active pack's KPIs against its healthy ranges. Benchmarks are synthetic and labelled as such."""

    as_of: date
    pack_ref: str
    benchmarks_synthetic: Literal[True] = True
    kpis: list[KpiRow]

    @classmethod
    def build(cls, c: Computed, as_of: date) -> "KpiResponse":
        s = c.store
        rows = [KpiRow(kpi_id=b.kpi_id, label=b.label, status=b.status,
                       value=s.get(b.value_fact_id) if b.value_fact_id else None,
                       healthy_min=s.get(b.healthy_min_fact_id) if b.healthy_min_fact_id else None,
                       healthy_max=s.get(b.healthy_max_fact_id) if b.healthy_max_fact_id else None)
                for b in c.benchmarks]
        return cls(as_of=as_of, pack_ref=c.inputs.pack.ref, kpis=rows)
