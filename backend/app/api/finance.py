"""Facts, the explain_fact trace, P&L, cash position, forecast, and pack KPIs with benchmarks.

Every number in these responses is an engine Fact (invariant 4), computed for the simulated today under the
business's active Skill Pack.
"""

from typing import Annotated

from fastapi import APIRouter, Query

from app.api.deps import BusinessId, RuntimeDep
from app.api.views import CashPosition, FactList, ForecastResponse, KpiResponse, Period, PnlResponse
from app.firewall.explain import FactTrace, explain
from app.services.finance import resolver

router = APIRouter(tags=["finance"])


@router.get("/businesses/{business_id}/facts", response_model=FactList)
def get_facts(
    business_id: BusinessId,
    rt: RuntimeDep,
    prefix: Annotated[str | None, Query(max_length=128, description="e.g. cash. or forecast.30d.")] = None,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=2000)] = 500,
) -> FactList:
    c = rt.facts(business_id)
    facts = sorted((f for f in c.store if prefix is None or f.id.startswith(prefix)), key=lambda f: f.id)
    return FactList(as_of=rt.clock.today(), pack_ref=c.inputs.pack.ref, total=len(facts),
                    facts=facts[offset:offset + limit])


@router.get("/businesses/{business_id}/facts/{fact_id}/explain", response_model=FactTrace)
def explain_fact(
    business_id: BusinessId,
    fact_id: str,
    rt: RuntimeDep,
    max_rows: Annotated[int, Query(ge=1, le=1000)] = 50,
) -> FactTrace:
    """The fact, every fact it was computed from, and the source rows they cite (owner view, with row text)."""
    c = rt.facts(business_id)
    trace = explain(fact_id, c.store, resolver(c.inputs), max_rows=max_rows, include_text=True)
    rt.audit.append("tool.explain_fact", {"business_id": business_id, "fact_id": fact_id, "caller": "api",
                                          "facts": len(trace.facts), "rows_total": trace.rows_total})
    return trace


@router.get("/businesses/{business_id}/pnl", response_model=PnlResponse)
def get_pnl(business_id: BusinessId, rt: RuntimeDep, period: Period = "month") -> PnlResponse:
    """Cash-basis profit and loss per calendar month or ISO week (only days before today count)."""
    return PnlResponse.build(rt.facts(business_id), rt.clock.today(), period)


@router.get("/businesses/{business_id}/cash", response_model=CashPosition)
def get_cash(business_id: BusinessId, rt: RuntimeDep) -> CashPosition:
    """Cash balance per account and in total, buffer days and runway."""
    return CashPosition.build(rt.facts(business_id), rt.clock.today())


@router.get("/businesses/{business_id}/forecast", response_model=ForecastResponse)
def get_forecast(business_id: BusinessId, rt: RuntimeDep) -> ForecastResponse:
    return ForecastResponse.build(rt.facts(business_id), rt.clock.today())


@router.get("/businesses/{business_id}/kpis", response_model=KpiResponse)
def get_kpis(business_id: BusinessId, rt: RuntimeDep) -> KpiResponse:
    return KpiResponse.build(rt.facts(business_id), rt.clock.today())
