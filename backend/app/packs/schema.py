"""Pydantic schema for a Skill Pack file (`packs/<id>.yaml`). This module is the pack format.

A pack is trusted, versioned config for one kind of business. On the same ledger it changes:

- `categories`: how rows are categorized (ordered keyword rules, first match wins) and each category's engine kind,
  so P&L, margins and the forecast baseline all follow the pack.
- `seasonality`: month multipliers and a multiplier per holiday-calendar ID, applied by the forecast on top of
  its weekday baseline (`engine_doc()` produces exactly what `engine.pack_inputs.build_engine_pack` reads).
- `kpis`: which KPIs are computed and their healthy ranges for benchmarking (benchmarks are synthetic).
- `leak_detectors`: which registered detector functions run, by name, with params validated per detector.
- `financing_fit`: how well each financing product type suits this kind of business.
- `readiness`: weights, raw-value ranges and bands for the Readiness Passport.

A pack holds no money amounts: thresholds are ratios, counts and day windows, so it is currency- and
region-neutral. Holiday IDs are generic types (e.g. `major_festival`); the business's calendar maps them to dates.
Labels are UI text we wrote, never LLM output.
"""

from typing import Annotated, Any, Literal, get_args

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator

from app.engine.pack_inputs import CategoryKind

Slug = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]*$", max_length=64)]
Keyword = Annotated[str, StringConstraints(min_length=2, max_length=64, strip_whitespace=True, to_lower=True)]
Ratio = Annotated[float, Field(ge=0.0, le=1.0)]
Multiplier = Annotated[float, Field(gt=0.0, le=5.0)]
Label = Annotated[str, StringConstraints(min_length=1, max_length=80)]

FinancingProductType = Literal[
    "working_capital_loan",
    "inventory_financing",
    "invoice_financing",
    "merchant_cash_advance",
    "equipment_lease",
    "nano_loan",
    "overdraft",
]

ReadinessFactor = Literal[
    "inflow_regularity",
    "revenue_stability",
    "buffer_days",
    "collection_days",
    "payment_punctuality",
]
READINESS_FACTORS: tuple[str, ...] = get_args(ReadinessFactor)


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class MatchRule(_Strict):
    """A row matches if its channel equals one of `channel`, or its counterparty or description contains one of the
    keywords (case-insensitive substrings). Keep keywords specific: "emi" would match "premium".

    `direction` defaults from the category kind: revenue matches inflows, transfers both ways, the rest outflows.
    """

    channel: tuple[Keyword, ...] = ()
    counterparty: tuple[Keyword, ...] = ()
    description: tuple[Keyword, ...] = ()
    direction: Literal["in", "out", "any"] | None = None

    @model_validator(mode="after")
    def _not_empty(self) -> "MatchRule":
        if not self.channel and not self.counterparty and not self.description:
            raise ValueError("a match rule needs at least one channel, counterparty or description keyword")
        return self


class Category(_Strict):
    label: Label
    kind: CategoryKind
    scheduled: bool = False  # forecast from known scheduled items, so the weekday baseline leaves it out
    digital: bool = False  # revenue only: a traceable digital inflow (for fee KPIs and financing history)
    match: MatchRule | None = None  # None: never assigned by rules (e.g. only set by ingestion)

    @property
    def direction(self) -> Literal["in", "out", "any"]:
        if self.match and self.match.direction:
            return self.match.direction
        if self.kind == "transfer":
            return "any"
        return "in" if self.kind == "revenue" else "out"

    @model_validator(mode="after")
    def _digital_is_revenue(self) -> "Category":
        if self.digital and self.kind != "revenue":
            raise ValueError("only revenue categories can be digital")
        return self


class Seasonality(_Strict):
    months: dict[int, Multiplier]
    holidays: dict[Slug, Multiplier] = Field(default_factory=dict)  # holiday-calendar ID -> multiplier

    @field_validator("months")
    @classmethod
    def _twelve_months(cls, v: dict[int, float]) -> dict[int, float]:
        if set(v) != set(range(1, 13)):
            raise ValueError("months must have exactly the keys 1..12")
        return v


class HealthyRange(_Strict):
    min: float | None = None
    max: float | None = None

    @model_validator(mode="after")
    def _ordered(self) -> "HealthyRange":
        if self.min is None and self.max is None:
            raise ValueError("a healthy range needs min, max or both")
        if self.min is not None and self.max is not None and self.min > self.max:
            raise ValueError("healthy range min must be <= max")
        return self


class Kpi(_Strict):
    """A KPI and its healthy range.

    `source: ratio` is computed from categorized rows in the lookback window:
    |sum(numerator rows)| / |sum(denominator rows)| (signed amounts netted per side), where each side lists category IDs or engine kinds, and
    `complement` gives 1 - ratio (gross margin = 1 - cogs/revenue). `source: engine` names an engine metric
    (e.g. buffer_days) whose Fact the caller passes in for benchmarking.
    """

    id: Slug
    label: Label
    unit: Literal["ratio", "days", "count"]
    healthy: HealthyRange
    source: Literal["ratio", "engine"]
    numerator: tuple[Slug, ...] = ()
    denominator: tuple[Slug, ...] = ()
    complement: bool = False
    metric: Slug | None = None

    @model_validator(mode="after")
    def _source_fields(self) -> "Kpi":
        if self.source == "ratio":
            if not self.numerator or not self.denominator or self.metric is not None or self.unit != "ratio":
                raise ValueError(f"ratio KPI {self.id} needs unit ratio, numerator and denominator, and no metric")
        elif self.metric is None or self.numerator or self.denominator or self.complement:
            raise ValueError(f"engine KPI {self.id} needs metric and no numerator, denominator or complement")
        return self


class DetectorConfig(_Strict):
    """A leak detector referenced by registered name. `params` are validated by the detector's own model at load."""

    detector: Slug
    label: Label
    params: dict[str, Any] = Field(default_factory=dict)


class FinancingFit(_Strict):
    fit: Ratio
    reason: Label


class ReadinessFactorSpec(_Strict):
    """Linear map of a raw factor value onto 0..1: `worst` scores 0, `best` scores 1, clipped.

    `best` below `worst` means lower is better (collection_days).
    """

    weight: Ratio
    worst: float
    best: float

    @model_validator(mode="after")
    def _distinct(self) -> "ReadinessFactorSpec":
        if self.worst == self.best:
            raise ValueError("worst and best must differ")
        return self


class ReadinessBand(_Strict):
    id: Slug
    label: Annotated[str, StringConstraints(min_length=1, max_length=30)]
    min_score: Ratio


class Readiness(_Strict):
    factors: dict[ReadinessFactor, ReadinessFactorSpec]
    bands: tuple[ReadinessBand, ...]  # highest first; the last starts at 0

    @model_validator(mode="after")
    def _check(self) -> "Readiness":
        if set(self.factors) != set(READINESS_FACTORS):
            raise ValueError(f"readiness needs exactly the factors {list(READINESS_FACTORS)}")
        total = sum(f.weight for f in self.factors.values())
        if abs(total - 1.0) > 1e-6:
            raise ValueError(f"readiness weights must sum to 1, got {total:.4f}")
        scores = [b.min_score for b in self.bands]
        if not scores or scores != sorted(set(scores), reverse=True):
            raise ValueError("readiness bands must be listed from highest to lowest min_score, without ties")
        if scores[-1] != 0.0:
            raise ValueError("the lowest readiness band must start at 0")
        return self


class Pack(_Strict):
    id: Slug
    version: int = Field(ge=1)
    display_name: Annotated[str, StringConstraints(min_length=1, max_length=40)]
    benchmarks_synthetic: Literal[True]  # benchmarks are synthetic and must be labelled as such
    kpi_lookback_days: int = Field(default=90, ge=28, le=365)
    categories: dict[Slug, Category]  # ordered: the first matching rule wins
    seasonality: Seasonality
    kpis: tuple[Kpi, ...]
    leak_detectors: tuple[DetectorConfig, ...]
    financing_fit: dict[FinancingProductType, FinancingFit]
    readiness: Readiness

    @property
    def ref(self) -> str:
        """Stable reference used as the provenance of values that come from this pack's config."""
        return f"pack:{self.id}@{self.version}"

    def engine_doc(self) -> dict[str, Any]:
        """The slice `engine.pack_inputs.build_engine_pack` reads: category kinds and seasonality."""
        return {
            "id": self.id,
            "categories": {cid: {"kind": c.kind, "scheduled": c.scheduled} for cid, c in self.categories.items()},
            "seasonality": {"months": dict(self.seasonality.months), "holidays": dict(self.seasonality.holidays)},
        }

    @model_validator(mode="after")
    def _cross_refs(self) -> "Pack":
        if not any(c.kind == "revenue" for c in self.categories.values()):
            raise ValueError("a pack needs at least one revenue category")
        refs = set(self.categories) | set(get_args(CategoryKind))
        kpi_ids = [k.id for k in self.kpis]
        if len(kpi_ids) != len(set(kpi_ids)):
            raise ValueError("kpi ids must be unique")
        for k in self.kpis:
            missing = (set(k.numerator) | set(k.denominator)) - refs
            if missing:
                raise ValueError(f"KPI {k.id} references unknown categories or kinds: {sorted(missing)}")
        names = [d.detector for d in self.leak_detectors]
        if len(names) != len(set(names)):
            raise ValueError("each leak detector may appear once per pack")
        return self
