"""The slice of a Skill Pack the finance engine reads: category kinds and forecast seasonality.

The full pack model (prompt 5) holds much more (KPIs, detectors, financing weights); it only has to produce an
`EnginePack`. Holiday dates come from the business's holiday calendar (config, region-neutral); the pack supplies
the multiplier per holiday ID.
"""

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

CategoryKind = Literal["revenue", "cogs", "operating", "owner", "transfer", "opening"]


class CategorySpec(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: CategoryKind
    # Scheduled categories are forecast from known ScheduledItems, so the weekday baseline leaves them out
    # (otherwise rent or payroll would be counted twice).
    scheduled: bool = False


class HolidayWindow(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    name: str
    start: date
    end: date
    multiplier: float = Field(gt=0)


class EnginePack(BaseModel):
    model_config = ConfigDict(frozen=True)

    pack_id: str
    categories: dict[str, CategorySpec]
    month_multipliers: dict[int, float] = Field(default_factory=dict)
    holidays: tuple[HolidayWindow, ...] = ()

    def kind_of(self, category: str, amount_minor: int) -> CategoryKind:
        """Unknown categories are treated as operating costs (outflows) or revenue (inflows), never dropped."""
        spec = self.categories.get(category)
        if spec is not None:
            return spec.kind
        return "revenue" if amount_minor > 0 else "operating"

    def is_scheduled(self, category: str) -> bool:
        spec = self.categories.get(category)
        return spec is not None and spec.scheduled

    def multiplier(self, day: date) -> float:
        """Seasonality multiplier for one day: month multiplier times the strongest holiday window covering it."""
        m = self.month_multipliers.get(day.month, 1.0)
        h = max((w.multiplier for w in self.holidays if w.start <= day <= w.end), default=1.0)
        return m * h


def build_engine_pack(pack: dict[str, Any], calendar: list[dict[str, Any]]) -> EnginePack:
    """Combine a pack document (its `categories` and `seasonality` sections) with a holiday calendar."""
    season = pack.get("seasonality", {})
    holiday_mult: dict[str, float] = season.get("holidays", {})
    windows = tuple(
        HolidayWindow(id=h["id"], name=h["name"], start=h["start"], end=h["end"], multiplier=holiday_mult[h["id"]])
        for h in calendar
        if h["id"] in holiday_mult
    )
    return EnginePack(
        pack_id=pack["id"],
        categories={k: CategorySpec(**v) for k, v in pack["categories"].items()},
        month_multipliers={int(k): float(v) for k, v in season.get("months", {}).items()},
        holidays=windows,
    )
