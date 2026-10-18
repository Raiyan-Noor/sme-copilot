"""Policy loader: reads policy.yaml into typed rules (invariants 1, 3, 5).

Lookups fail closed: a tool not named in T1-T3 has no tier and is denied. T4 never lists tools. System tools
(`anchor`) are not proposable by the planner. T1 entries may be glob patterns (`get_*`); T2 and T3 must be exact
names, so a new action tool cannot slip in through a pattern.
"""

from fnmatch import fnmatchcase
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict

Tier = Literal["T1", "T2", "T3", "T4"]

POLICY_PATH = Path(__file__).with_name("policy.yaml")


class FrequencyCap(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max: int
    per: str
    window_days: int


class T2Rule(BaseModel):
    """Hard ceilings for one T2 tool. A standing mandate may lower these but never raise them."""

    model_config = ConfigDict(extra="forbid")

    amount_arg: str
    max_amount_minor: int
    allowlist_arg: str
    frequency: FrequencyCap | None = None


class T3Rule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    requires_out_of_band_call_script: bool = False


class Policy(BaseModel):
    model_config = ConfigDict(frozen=True)

    default_decision: Literal["deny"]
    untrusted_escalate_to: Literal["T3"]
    approval_ttl_days: int
    standing_mandate_max_days: int
    t1_patterns: tuple[str, ...]
    t2: dict[str, T2Rule]
    t3: dict[str, T3Rule]
    t4_categories: tuple[str, ...]
    system_tools: dict[str, dict[str, Any]]

    def tier_of(self, tool: str) -> Tier | None:
        """Tier for a planner-proposable tool, or None if unknown (and therefore denied)."""
        if tool in self.system_tools:
            return None
        if tool in self.t2:
            return "T2"
        if tool in self.t3:
            return "T3"
        if any(fnmatchcase(tool, p) for p in self.t1_patterns):
            return "T1"
        return None


def parse_policy(raw: dict[str, Any]) -> Policy:
    tiers = raw["tiers"]
    if tiers["T4"]["tools"]:
        raise ValueError("invariant 5: T4 must list no tools")
    for name in list(tiers["T2"]["tools"]) + list(tiers["T3"]["tools"]):
        if any(ch in name for ch in "*?["):
            raise ValueError(f"T2/T3 tool names must be exact, got pattern {name!r}")
    return Policy(
        default_decision=raw["default_decision"],
        untrusted_escalate_to=raw["untrusted_provenance"]["escalate_to"],
        approval_ttl_days=raw["approvals"]["ttl_days"],
        standing_mandate_max_days=raw["approvals"]["standing_mandate_max_days"],
        t1_patterns=tuple(tiers["T1"]["tools"]),
        t2={k: T2Rule(**v) for k, v in tiers["T2"]["tools"].items()},
        t3={k: T3Rule(**(v or {})) for k, v in tiers["T3"]["tools"].items()},
        t4_categories=tuple(tiers["T4"].get("refused_request_categories", [])),
        system_tools=raw.get("system_tools", {}),
    )


@lru_cache
def load_policy(path: Path = POLICY_PATH) -> Policy:
    return parse_policy(yaml.safe_load(Path(path).read_text(encoding="utf-8")))
