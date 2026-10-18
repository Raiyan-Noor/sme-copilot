"""The Fact model (invariant 4, Numeric Firewall).

Every number or date shown to the owner is a Fact computed in code. The LLM never sees or writes the value; it
writes a `{fact:<id>}` placeholder and the renderer substitutes `display`. A Fact traces to ledger rows through
`source_row_ids` (rows it read directly) and `inputs` (other Facts it was computed from), so `explain_fact` can
walk any number back to the rows it came from.
"""

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

FactUnit = Literal["money", "ratio", "days", "date", "count"]


class Fact(BaseModel):
    """One computed value.

    `value` is the machine value: integer minor units for money (with `currency` set), a float for ratios and
    days, an ISO date for dates, an int for counts, or None when there is nothing to report (e.g. runway that does
    not run out within the forecast horizon; `display` then says so in words).
    """

    model_config = ConfigDict(frozen=True)

    # Must start with a letter so a placeholder like {fact:1500} can never smuggle a number past the digit check;
    # same grammar as firewall/digit_check.py.
    id: str = Field(pattern=r"^[a-z][a-z0-9_.:\-]{0,127}$")
    value: int | float | date | None
    unit: FactUnit
    display: str
    source_row_ids: tuple[str, ...]
    computed_by: str
    currency: str | None = None
    inputs: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _check(self) -> "Fact":
        if self.unit == "money":
            if self.currency is None:
                raise ValueError(f"money fact {self.id} needs a currency")
            if self.value is not None and (isinstance(self.value, bool) or not isinstance(self.value, int)):
                raise ValueError(f"money fact {self.id} must be integer minor units")
        if not self.source_row_ids and not self.inputs:
            raise ValueError(f"fact {self.id} traces to nothing: needs source_row_ids or inputs")
        return self
