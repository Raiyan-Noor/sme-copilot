"""Simulated clock: read and fast-forward (it never moves backwards).

Fast-forwarding runs the overnight job for every business as of the new date: invoice reminders proposed through
each business's gateway (executed only under the owner's signed standing mandate), then the Morning Brief. The job
runs once per advance, as of the new date, however many days were skipped.
"""

from datetime import date

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.api.deps import RuntimeDep
from app.services.businesses import list_businesses
from app.services.overnight import OvernightReport, run_overnight

router = APIRouter(tags=["clock"])


class ClockState(BaseModel):
    today: date
    start: date
    offset_days: int


class AdvanceRequest(BaseModel):
    days: int = Field(ge=1, le=365)
    run_overnight: bool = Field(default=True, description="Run reminders and the Morning Brief after moving")


class AdvanceResult(ClockState):
    overnight: list[OvernightReport] = []


def _state(rt) -> ClockState:
    clock = rt.clock
    return ClockState(today=clock.today(), start=clock.start, offset_days=clock.offset_days)


@router.get("/clock", response_model=ClockState)
def get_clock(rt: RuntimeDep) -> ClockState:
    return _state(rt)


@router.post("/clock/advance", response_model=AdvanceResult)
def advance(body: AdvanceRequest, rt: RuntimeDep) -> AdvanceResult:
    """Move the simulated clock forward, then run the overnight job for each business (unless turned off)."""
    rt.advance_clock(body.days)
    reports = [run_overnight(rt, b.id) for b in list_businesses(rt.data_dir)] if body.run_overnight else []
    return AdvanceResult(**_state(rt).model_dump(), overnight=reports)
