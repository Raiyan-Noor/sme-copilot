"""Readiness score and band from raw factor Facts, using the pack's weights, ranges and bands.

The engine (build prompt 13) computes the five raw factors as Facts; this module only applies pack config, so the
same raw factors score differently under a different pack. Every output number is a Fact whose `inputs` trace
back to the raw factor Facts (invariant 4).
"""

from collections.abc import Mapping

from pydantic import BaseModel, ConfigDict

from app.firewall.fact import Fact
from app.packs.schema import READINESS_FACTORS, Pack


class ReadinessResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    score: Fact
    factor_scores: dict[str, Fact]
    band_id: str
    band_label: str


def _pct(v: float) -> str:
    return f"{v * 100:.0f}%"


def readiness_score(raw: Mapping[str, Fact], pack: Pack) -> ReadinessResult:
    """Normalize each raw factor onto 0..1 with the pack's worst/best, weight it, and pick the band."""
    missing = [f for f in READINESS_FACTORS if f not in raw]
    if missing:
        raise ValueError(f"readiness needs raw facts for {missing}")
    factor_scores: dict[str, Fact] = {}
    total = 0.0
    for name in READINESS_FACTORS:
        spec, fact = pack.readiness.factors[name], raw[name]
        if not isinstance(fact.value, int | float):
            raise ValueError(f"readiness factor {name} must be numeric")
        score = min(1.0, max(0.0, (float(fact.value) - spec.worst) / (spec.best - spec.worst)))
        total += spec.weight * score
        factor_scores[name] = Fact(id=f"readiness.factor.{name}", value=score, unit="ratio", display=_pct(score),
                                   source_row_ids=(), inputs=(fact.id,),
                                   computed_by=f"packs.readiness.readiness_score[{pack.ref}]")
    total = round(total, 6)
    band = next(b for b in pack.readiness.bands if total >= b.min_score)
    score_fact = Fact(id="readiness.score", value=total, unit="ratio", display=_pct(total), source_row_ids=(),
                      inputs=tuple(f.id for f in factor_scores.values()),
                      computed_by=f"packs.readiness.readiness_score[{pack.ref}]")
    return ReadinessResult(score=score_fact, factor_scores=factor_scores, band_id=band.id, band_label=band.label)
