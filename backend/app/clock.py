"""Simulated clock (fast-forward for the demo).

The only place the backend reads the current time; never use datetime.now() elsewhere. Dates are facts too
(invariant 4). Engine functions take a `Clock` and read only `today()`, so they stay pure and replayable.
"""

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Protocol


class Clock(Protocol):
    def today(self) -> date: ...


@dataclass(frozen=True)
class FixedClock:
    """A clock pinned to one date. Used by tests, golden files and the seed generator."""

    as_of: date

    def today(self) -> date:
        return self.as_of


@dataclass
class SimClock:
    """The app's simulated clock: starts at a configured date and only moves when the demo fast-forwards it."""

    start: date
    offset_days: int = 0

    def today(self) -> date:
        return self.start + timedelta(days=self.offset_days)

    def advance(self, days: int) -> date:
        if days < 0:
            raise ValueError("the simulated clock only moves forward")
        self.offset_days += days
        return self.today()
