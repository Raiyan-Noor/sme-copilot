"""Simulated clock (fast-forward for the demo).

The only place the backend reads the current time; never use datetime.now() elsewhere. Dates are facts too
(invariant 4). Engine functions take a `Clock` and read only `today()`, so they stay pure and replayable.

`SimClock.now()` adds a time of day for the audit log (invariant 7): each simulated day begins at 07:00 when the clock
moves to it (the demo fast-forwards to "tomorrow 7:00"), then time passes at the real rate until 23:59:59. Engine
functions never read it. `FixedClock` has no time of day, so test and golden logs stay byte-for-byte replayable.
"""

import time as walltime
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Protocol

DAY_BEGINS = time(7, 0)
DAY_ENDS = time(23, 59, 59)


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
    day_began_at: float | None = None  # wall-clock epoch seconds at which the current simulated day was 07:00

    def today(self) -> date:
        return self.start + timedelta(days=self.offset_days)

    def now(self) -> datetime:
        """Simulated date and time of day: 07:00 when the day began, plus the real time elapsed since."""
        if self.day_began_at is None:
            self.day_began_at = walltime.time()
        elapsed = max(0.0, walltime.time() - self.day_began_at)
        began = datetime.combine(self.today(), DAY_BEGINS)
        return min(began + timedelta(seconds=elapsed), datetime.combine(self.today(), DAY_ENDS))

    def advance(self, days: int) -> date:
        if days < 0:
            raise ValueError("the simulated clock only moves forward")
        self.offset_days += days
        if days:
            self.day_began_at = walltime.time()
        return self.today()
