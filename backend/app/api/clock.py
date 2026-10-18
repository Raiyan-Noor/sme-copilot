"""Simulated clock: read and fast-forward (it never moves backwards). The overnight job (reminders, then the
Morning Brief) hooks into advance in build prompt 14."""

from datetime import date

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.api.deps import RuntimeDep

router = APIRouter(tags=["clock"])


class ClockState(BaseModel):
    today: date
    start: date
    offset_days: int


class AdvanceRequest(BaseModel):
    days: int = Field(ge=1, le=365)


def _state(rt) -> ClockState:
    clock = rt.clock
    return ClockState(today=clock.today(), start=clock.start, offset_days=clock.offset_days)


@router.get("/clock", response_model=ClockState)
def get_clock(rt: RuntimeDep) -> ClockState:
    return _state(rt)


@router.post("/clock/advance", response_model=ClockState)
def advance(body: AdvanceRequest, rt: RuntimeDep) -> ClockState:
    rt.advance_clock(body.days)
    return _state(rt)
