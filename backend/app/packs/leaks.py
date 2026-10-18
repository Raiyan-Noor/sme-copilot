"""Run the active pack's leak detectors: (ledger snapshot, pack, clock) -> list[Fact].

Each Fact is one finding: yearly impact in minor units, evidence in source_row_ids (invariant 4).
"""

from app.clock import Clock
from app.firewall.fact import Fact
from app.ledger.snapshot import LedgerSnapshot
from app.packs.ledger_view import frame
from app.packs.registry import DetectorContext, get_detector
from app.packs.schema import Pack


def detector_labels(pack: Pack) -> dict[str, str]:
    """Owner-facing label per detector name, from the pack."""
    return {d.detector: d.label for d in pack.leak_detectors}


def run_leak_detectors(snapshot: LedgerSnapshot, pack: Pack, clock: Clock) -> list[Fact]:
    """All findings from the pack's detectors, in pack order, then by fact ID."""
    df = frame(snapshot, pack)
    ctx = DetectorContext(pack=pack, today=clock.today(), currency=snapshot.currency)
    facts: list[Fact] = []
    for cfg in pack.leak_detectors:
        spec = get_detector(cfg.detector)
        found = spec.fn(df, spec.params_model.model_validate(cfg.params), ctx)
        facts.extend(sorted(found, key=lambda f: f.id))
    return facts
