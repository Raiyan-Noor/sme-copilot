"""Morning Brief and leak routes. Presentation only: every figure is an engine Fact (invariant 4), and the brief's
prose carries {fact:id} placeholders that the UI resolves from its `facts`."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.agent import brief as brief_writer
from app.agent.brief import MorningBrief
from app.agent.context import load_profile
from app.agent.tools import LEAK_DETAIL_LABELS, leak_subject
from app.api.deps import BusinessId, RuntimeDep
from app.firewall.fact import Fact
from app.packs.leaks import detector_labels
from app.services.overnight import OvernightReport, run_overnight

router = APIRouter(tags=["brief"])


class LeakDetail(BaseModel):
    label: str
    fact: Fact


class LeakView(BaseModel):
    id: str
    detector: str
    label: str
    about: str | None
    subject: dict[str, str]
    yearly_impact: Fact
    details: list[LeakDetail]


@router.get("/businesses/{business_id}/brief", response_model=MorningBrief)
def get_brief(business_id: BusinessId, rt: RuntimeDep) -> MorningBrief:
    """The latest Morning Brief (written by the overnight job). 404 until the first one exists."""
    with rt.business(business_id):
        pass
    found = brief_writer.latest(rt.data_dir / business_id)
    if found is None:
        raise HTTPException(404, "no brief yet: advance the clock or POST /businesses/{id}/overnight")
    return found


@router.post("/businesses/{business_id}/overnight", response_model=OvernightReport)
def run_overnight_now(business_id: BusinessId, rt: RuntimeDep, reminders: bool = True) -> OvernightReport:
    """Run the overnight job now without moving the clock: reminders through the gateway, then the brief."""
    return run_overnight(rt, business_id, reminders=reminders)


@router.get("/businesses/{business_id}/leaks", response_model=list[LeakView])
def get_leaks(business_id: BusinessId, rt: RuntimeDep) -> list[LeakView]:
    """Every leak finding, largest yearly impact first, with its detail facts. Open any fact with explain_fact
    to see the evidence rows."""
    computed = rt.facts(business_id)
    labels = detector_labels(computed.inputs.pack)
    names = load_profile(computed, rt.settings.seed_dir).counterparty_names
    out = []
    for f in sorted(computed.leaks, key=lambda f: (-f.impact.value, f.id)):
        out.append(LeakView(
            id=f.id, detector=f.detector, label=labels.get(f.detector, f.detector), subject=f.subject,
            about=leak_subject(f, computed.inputs.products, names), yearly_impact=f.impact,
            details=[LeakDetail(label=LEAK_DETAIL_LABELS.get(d.id.rsplit(".", 1)[1], d.id.rsplit(".", 1)[1]),
                                fact=d) for d in f.details]))
    return out
