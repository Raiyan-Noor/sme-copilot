"""The synthetic financing catalog (`financing_catalog.yaml`): products, machine-readable eligibility rules and the
repayment-safe sizing parameters, validated here.

A rule is `{rule: <kind>, value: <threshold>}`. RULES says, for each kind, which engine metric Fact it reads, how
it compares, and the unit of the threshold. Adding a rule kind means adding a metric in engine/financing.py and an
entry here; the YAML cannot add code. Every product is small working-capital or asset finance: Tier 4 actions
(large debt among them) have no product and never will (invariant 5).
"""

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from app.packs.schema import FinancingProductType

CATALOG_PATH = Path(__file__).with_name("financing_catalog.yaml")

RuleKind = Literal[
    "min_history_months",
    "min_digital_history_months",
    "min_digital_share",
    "min_avg_monthly_revenue_minor",
    "min_readiness_score",
    "min_buffer_days",
    "max_collection_days",
    "min_payment_punctuality",
    "min_invoice_revenue_share",
]


@dataclass(frozen=True)
class RuleSpec:
    metric: str  # fact ID of the engine metric the rule reads
    op: Literal[">=", "<="]
    unit: Literal["count", "ratio", "money", "days"]
    label: str  # owner-facing, digit-free


RULES: dict[str, RuleSpec] = {
    "min_history_months": RuleSpec("financing.metric.history_months", ">=", "count", "Months of bank history"),
    "min_digital_history_months": RuleSpec("financing.metric.digital_history_months", ">=", "count",
                                           "Months of digital sales history"),
    "min_digital_share": RuleSpec("financing.metric.digital_share", ">=", "ratio", "Digital share of sales"),
    "min_avg_monthly_revenue_minor": RuleSpec("financing.metric.avg_monthly_revenue", ">=", "money",
                                              "Average monthly sales"),
    "min_readiness_score": RuleSpec("readiness.score", ">=", "ratio", "Readiness score"),
    "min_buffer_days": RuleSpec("cash.buffer_days", ">=", "days", "Cash buffer"),
    "max_collection_days": RuleSpec("passport.raw.collection_days", "<=", "days", "Days to collect from customers"),
    "min_payment_punctuality": RuleSpec("passport.raw.payment_punctuality", ">=", "ratio",
                                        "Supplier bills paid on time"),
    "min_invoice_revenue_share": RuleSpec("financing.metric.invoice_revenue_share", ">=", "ratio",
                                          "Share of sales from customer invoices"),
}

Id = Annotated[str, StringConstraints(pattern=r"^prd_[a-z][a-z_]*$", max_length=48)]
Name = Annotated[str, StringConstraints(min_length=1, max_length=60, pattern=r"^[^0-9]*$")]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Rule(_Strict):
    rule: RuleKind
    value: float

    @property
    def spec(self) -> RuleSpec:
        return RULES[self.rule]

    @model_validator(mode="after")
    def _units(self) -> "Rule":
        unit = RULES[self.rule].unit
        if unit == "ratio" and not 0.0 <= self.value <= 1.0:
            raise ValueError(f"{self.rule} is a ratio between 0 and 1")
        if unit in ("count", "money") and self.value != int(self.value):
            raise ValueError(f"{self.rule} needs a whole number")
        if self.value < 0:
            raise ValueError(f"{self.rule} cannot be negative")
        return self


class Product(_Strict):
    id: Id
    name: Name
    lender: Name
    type: FinancingProductType
    min_amount_minor: int = Field(gt=0)
    max_amount_minor: int = Field(gt=0)
    step_minor: int = Field(gt=0)
    term_months: int = Field(ge=1, le=36)
    monthly_rate: float = Field(ge=0.0, le=0.1)
    rules: tuple[Rule, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _check(self) -> "Product":
        if self.min_amount_minor > self.max_amount_minor:
            raise ValueError(f"{self.id}: min amount above max amount")
        kinds = [r.rule for r in self.rules]
        if len(kinds) != len(set(kinds)):
            raise ValueError(f"{self.id}: each rule kind may appear once")
        return self


class Sizing(_Strict):
    revenue_drop: float = Field(gt=0.0, lt=1.0)
    max_share_of_stressed_surplus: float = Field(gt=0.0, le=1.0)
    liquidity_horizon_months: int = Field(ge=1, le=3)


class Catalog(_Strict):
    synthetic: Literal[True]
    version: int = Field(ge=1)
    currency: Annotated[str, StringConstraints(pattern=r"^[A-Z]{3}$")]
    sizing: Sizing
    products: tuple[Product, ...] = Field(min_length=6, max_length=10)

    @property
    def ref(self) -> str:
        """Provenance prefix for values that come from the catalog (`catalog:v1#prd_nano.rules.min_...`)."""
        return f"catalog:v{self.version}"

    def get(self, product_id: str) -> Product | None:
        return next((p for p in self.products if p.id == product_id), None)

    @model_validator(mode="after")
    def _unique(self) -> "Catalog":
        ids = [p.id for p in self.products]
        if len(ids) != len(set(ids)):
            raise ValueError("product ids must be unique")
        return self


@lru_cache(maxsize=1)
def load_catalog(path: Path = CATALOG_PATH) -> Catalog:
    return Catalog.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
