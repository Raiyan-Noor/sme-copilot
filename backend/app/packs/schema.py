"""Pydantic schema for a Skill Pack: the YAML frontmatter of a skill.md file (packs/skill.py, docs/skills/FORMAT.md).

A pack is trusted, versioned config for one kind of business. On the same ledger it changes:

- `categories`: how rows are categorized (ordered keyword rules, first match wins) and each category's engine kind,
  so P&L, margins and the forecast baseline all follow the pack.
- `seasonality`: month multipliers and a multiplier per holiday-calendar ID, applied by the forecast on top of
  its weekday baseline (`engine_doc()` produces exactly what `engine.pack_inputs.build_engine_pack` reads).
- `kpis`: which KPIs are computed and their healthy ranges for benchmarking (benchmarks are synthetic).
- `leak_detectors`: which registered detector functions run, by name, with params validated per detector.
- `financing_fit`: how well each financing product type suits this kind of business.
- `readiness`: weights, raw-value ranges and bands for the Readiness Passport.
- `data_needs`: what onboarding asks the owner to upload (products, sales, ad spend ...), why, and the CSV columns.
- `advisor_questions`: what an experienced advisor for this kind of business would ask, with a one-line "why I'm
  asking"; each answer becomes an owner-stated Fact or a detector setting the engine uses.
- `business_types`: words in an owner's own description of the business that pick this pack at onboarding.

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


DataKind = Literal["bank", "sales", "products", "ad_spend"]


class DataNeed(_Strict):
    """One thing onboarding asks for. `kind` names the CSV the upload must match (ledger/records.py)."""

    id: Slug
    kind: DataKind
    ask: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    why: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    required: bool = False
    # What the brief says when the owner skipped it: "KaChing could also check <unlocks> if you add <label>."
    label: Label
    unlocks: Label


class AnswerOption(_Strict):
    label: Label  # UI text we wrote (may hold digits: it is shown to the owner, never to the planner)
    value: float | None = None  # None: "not sure", which leaves the pack default in place


class AnswerEffect(_Strict):
    """What an answer changes. Exactly one of: an owner-stated Fact (`fact`), or a detector param (`detector`)."""

    fact: Slug | None = None
    unit: Literal["ratio", "days", "count"] | None = None
    detector: Slug | None = None
    param: Slug | None = None

    @model_validator(mode="after")
    def _one(self) -> "AnswerEffect":
        if (self.fact is None) == (self.detector is None):
            raise ValueError("an answer effect sets either a fact or a detector param")
        if self.fact is not None and self.unit is None:
            raise ValueError("a fact effect needs a unit")
        if self.detector is not None and self.param is None:
            raise ValueError("a detector effect needs a param")
        return self


class AdvisorQuestion(_Strict):
    id: Slug
    ask: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    why: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    options: tuple[AnswerOption, ...] = Field(min_length=2, max_length=6)
    effect: AnswerEffect


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
    business_types: tuple[Keyword, ...] = ()
    data_needs: tuple[DataNeed, ...] = ()
    advisor_questions: tuple[AdvisorQuestion, ...] = ()

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
        for q in self.advisor_questions:
            if q.effect.detector is not None and q.effect.detector not in names:
                raise ValueError(f"question {q.id} sets a param of {q.effect.detector}, which this pack does not run")
        for group in (self.data_needs, self.advisor_questions):
            ids = [g.id for g in group]
            if len(ids) != len(set(ids)):
                raise ValueError("data need and question ids must be unique")
        return self
