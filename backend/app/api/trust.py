"""Trust routes: the limits the owner has signed, as the Trust screen shows them, and the latest red-team results.

Read-only presentation. Tiers and caps come straight from policy.yaml and active standing mandates from the
gateway's store of verified signatures. Nothing here can change a tier or a cap: a new limit takes effect only
through POST /gateway/mandates with the owner's signature (invariants 1 and 6). Red-team figures are passed through
from docs/results/redteam.json exactly as `make redteam` wrote them; nothing is computed or rounded here
(invariant 8).
"""

import json
from datetime import date

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict

from app.agent.context import load_profile
from app.agent.tools import TRUSTED_SCHEDULE_SOURCES
from app.api.deps import BusinessId, RuntimeDep
from app.gateway.policy import FrequencyCap

router = APIRouter(tags=["trust"])

# Which scheduled items supply the IDs a T2 tool's allow-list is checked against.
_ALLOWLIST_KIND = {"customer_id": "receivable", "payee_id": "payable"}


class Counterparty(BaseModel):
    id: str
    name: str | None


class StandingMandateView(BaseModel):
    mandate_id: int
    max_amount_minor: int
    allowlist: list[str]
    expiry: date
    signed_on: date
    record_hash: str


class T2Limit(BaseModel):
    """A T2 tool: its policy.yaml ceiling, the owner's active standing mandate (if any) and who it could cover."""

    tool: str
    policy_max_amount_minor: int
    allowlist_arg: str
    frequency: FrequencyCap | None
    active: StandingMandateView | None
    candidates: list[Counterparty]


class T3Limit(BaseModel):
    tool: str
    requires_out_of_band_call_script: bool


class LimitsView(BaseModel):
    currency: str
    owner_key_enrolled: bool
    approval_ttl_days: int
    standing_mandate_max_days: int
    t1_tools: list[str]
    t2: list[T2Limit]
    t3: list[T3Limit]
    t4_categories: list[str]


@router.get("/businesses/{business_id}/limits", response_model=LimitsView)
def get_limits(business_id: BusinessId, rt: RuntimeDep) -> LimitsView:
    """Every tier with its tools, the hard caps from policy.yaml and the standing mandates the owner has signed."""
    gw = rt.gateway(business_id)
    computed = rt.facts(business_id)
    names = load_profile(computed, rt.settings.seed_dir).counterparty_names
    today = rt.clock.today()
    policy = gw.policy

    t2 = []
    for tool, rule in policy.t2.items():
        kind = _ALLOWLIST_KIND.get(rule.allowlist_arg)
        ids = sorted({i.counterparty_id for i in computed.inputs.scheduled
                      if i.kind == kind and i.counterparty_id and i.source in TRUSTED_SCHEDULE_SOURCES})
        mandate = gw.store.active_standing(tool, today)
        active = None
        if mandate is not None and mandate.terms is not None:
            active = StandingMandateView(mandate_id=mandate.id, max_amount_minor=mandate.terms.max_amount_minor,
                                         allowlist=list(mandate.terms.allowlist), expiry=mandate.payload.expiry,
                                         signed_on=mandate.signed_on, record_hash=mandate.record_hash)
        t2.append(T2Limit(tool=tool, policy_max_amount_minor=rule.max_amount_minor, allowlist_arg=rule.allowlist_arg,
                          frequency=rule.frequency, active=active,
                          candidates=[Counterparty(id=i, name=names.get(i)) for i in ids]))

    return LimitsView(
        currency=computed.inputs.info.currency, owner_key_enrolled=gw.store.has_owner_key(),
        approval_ttl_days=policy.approval_ttl_days, standing_mandate_max_days=policy.standing_mandate_max_days,
        t1_tools=list(policy.t1_patterns), t2=t2,
        t3=[T3Limit(tool=k, requires_out_of_band_call_script=v.requires_out_of_band_call_script)
            for k, v in policy.t3.items()],
        t4_categories=list(policy.t4_categories))


class _Loose(BaseModel):
    model_config = ConfigDict(extra="ignore")


class RedteamDefense(_Loose):
    layer: str
    rule: str
    variants: int


class RedteamVariant(_Loose):
    variant: str
    driver: str
    blocked: bool


class RedteamAttack(_Loose):
    id: str
    name: str
    blocked: bool
    caught_by: list[RedteamDefense] = []
    variants: list[RedteamVariant] = []


class RedteamTask(_Loose):
    task: str
    business: str
    kind: str
    succeeded: bool


class RedteamProvider(_Loose):
    status: str
    reason: str | None = None
    recorded_models: dict[str, int] = {}
    attacks_run: int | None = None
    attacks_blocked: int | None = None
    attack_variants_run: int | None = None
    attack_variants_blocked: int | None = None
    live_llm_variants: int | None = None
    tasks_run: int | None = None
    tasks_succeeded: int | None = None
    attacks_caught_per_defense_layer: dict[str, int] = {}
    attacks: list[RedteamAttack] = []
    tasks: list[RedteamTask] = []


class RedteamReport(_Loose):
    generated_by: str
    mode: str
    commit: str | None = None
    data: str | None = None
    pending_attacks: dict[str, str] = {}
    providers: dict[str, RedteamProvider]


@router.get("/redteam", response_model=RedteamReport)
def get_redteam(rt: RuntimeDep) -> RedteamReport:
    """The latest `make redteam` results, as written. 404 until the suite has run."""
    path = rt.settings.redteam_results
    if not path.is_file():
        raise HTTPException(404, "no red-team results yet: run `make redteam`")
    return RedteamReport.model_validate(json.loads(path.read_text(encoding="utf-8")))
