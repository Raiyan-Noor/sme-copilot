"""Pack KPIs and benchmarking against the pack's healthy ranges (benchmarks are synthetic).

Ratio KPIs are computed here from categorized rows; engine KPIs (e.g. buffer_days) are passed in as engine Facts
keyed by metric name. Healthy-range bounds are Facts too (invariant 4). They come from pack config, not ledger
rows, so their provenance is a pack reference `pack:<id>@<version>#kpis.<kpi>.healthy` in source_row_ids;
explain_fact must render `pack:` references as "from the Skill Pack" rather than look them up as ledger rows.
"""

from collections.abc import Mapping
from datetime import timedelta
from typing import Literal

import pandas as pd
from pydantic import BaseModel, ConfigDict

from app.clock import Clock
from app.firewall.fact import Fact
from app.ledger.snapshot import LedgerSnapshot
from app.packs.ledger_view import frame
from app.packs.schema import Kpi, Pack

Status = Literal["below", "within", "above", "no_data"]


class Benchmark(BaseModel):
    """One KPI against its healthy range. Numbers live in the referenced Facts; this holds IDs and status."""

    model_config = ConfigDict(frozen=True)

    kpi_id: str
    label: str
    status: Status
    value_fact_id: str | None
    healthy_min_fact_id: str | None
    healthy_max_fact_id: str | None
    synthetic: Literal[True] = True


def _side(df: pd.DataFrame, refs: tuple[str, ...]) -> pd.DataFrame:
    return df[df["category"].isin(refs) | df["kind"].isin(refs)]


def _display(kpi: Kpi, value: float) -> str:
    if kpi.unit == "ratio":
        return f"{value * 100:.1f}%"
    return f"{value:.0f} days" if kpi.unit == "days" else f"{value:.0f}"


def compute_kpis(snapshot: LedgerSnapshot, pack: Pack, clock: Clock) -> list[Fact]:
    """Ratio KPIs over the pack's lookback window. A KPI with no rows or a zero denominator is omitted."""
    df = frame(snapshot, pack)
    end = pd.Timestamp(clock.today())
    df = df[(df["date"] > end - timedelta(days=pack.kpi_lookback_days)) & (df["date"] <= end)]
    facts = []
    for kpi in pack.kpis:
        if kpi.source != "ratio":
            continue
        num, den = _side(df, kpi.numerator), _side(df, kpi.denominator)
        # Net each side, then take the magnitude: revenue nets refunds (outflows in a revenue category), and a
        # supplier credit note reduces cogs, exactly as the engine's P&L does.
        den_total = abs(int(den["amount_minor"].sum()))
        if den_total == 0:
            continue
        value = float(abs(int(num["amount_minor"].sum())) / den_total)
        if kpi.complement:
            value = 1.0 - value
        rows = tuple(sorted(set(num["row_id"]) | set(den["row_id"])))
        facts.append(Fact(id=f"kpi.{kpi.id}", value=value, unit="ratio", display=_display(kpi, value),
                          source_row_ids=rows, computed_by=f"packs.benchmarks.compute_kpis[{pack.ref}]"))
    return facts


def _bound_fact(pack: Pack, kpi: Kpi, which: Literal["min", "max"]) -> Fact | None:
    value = getattr(kpi.healthy, which)
    if value is None:
        return None
    return Fact(id=f"benchmark.{kpi.id}.{which}", value=value, unit="days" if kpi.unit == "days" else (
        "count" if kpi.unit == "count" else "ratio"), display=_display(kpi, value),
        source_row_ids=(f"{pack.ref}#kpis.{kpi.id}.healthy",), computed_by="packs.benchmarks.benchmark")


def benchmark(kpi_facts: Mapping[str, Fact], pack: Pack) -> tuple[list[Benchmark], list[Fact]]:
    """Compare KPI values to healthy ranges.

    `kpi_facts` maps a ratio KPI's ID (from compute_kpis, key `kpi.<id>` or `<id>`) or an engine KPI's metric name
    to its Fact. Returns the benchmarks and the range-bound Facts they reference.
    """
    results, bounds = [], []
    for kpi in pack.kpis:
        key = kpi.metric if kpi.source == "engine" else kpi.id
        fact = kpi_facts.get(key) or kpi_facts.get(f"kpi.{key}")
        lo, hi = _bound_fact(pack, kpi, "min"), _bound_fact(pack, kpi, "max")
        bounds.extend(b for b in (lo, hi) if b is not None)
        status: Status = "no_data"
        if fact is not None and isinstance(fact.value, int | float):
            v = float(fact.value)
            status = ("below" if kpi.healthy.min is not None and v < kpi.healthy.min else
                      "above" if kpi.healthy.max is not None and v > kpi.healthy.max else "within")
        results.append(Benchmark(kpi_id=kpi.id, label=kpi.label, status=status,
                                 value_fact_id=fact.id if fact else None,
                                 healthy_min_fact_id=lo.id if lo else None, healthy_max_fact_id=hi.id if hi else None))
    return results, bounds
