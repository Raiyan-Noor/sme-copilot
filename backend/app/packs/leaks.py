"""Run the active pack's leak detectors: (ledger snapshot, pack, clock) -> findings / Facts.

Each Finding's impact Fact is the yearly impact in minor units with evidence in source_row_ids (invariant 4).
Detectors also read the business's own POS, purchasing and ad records (products, sale lines, purchase lines, ad spend) when the
pack enables a detector that needs them; without them those detectors find nothing.
"""

from app.clock import Clock
from app.firewall.fact import Fact
from app.ledger.pos import Product, SaleLine
from app.ledger.purchases import PurchaseLine
from app.ledger.records import AdSpendLine
from app.ledger.snapshot import LedgerSnapshot
from app.packs.ledger_view import frame
from app.packs.registry import DetectorContext, Finding, get_detector
from app.packs.schema import Pack


def detector_labels(pack: Pack) -> dict[str, str]:
    """Owner-facing label per detector name, from the pack."""
    return {d.detector: d.label for d in pack.leak_detectors}


def find_leaks(snapshot: LedgerSnapshot, pack: Pack, clock: Clock, *, products: tuple[Product, ...] = (),
               sale_lines: tuple[SaleLine, ...] = (), purchases: tuple[PurchaseLine, ...] = (),
               ad_spend: tuple[AdSpendLine, ...] = ()) -> list[Finding]:
    """All findings from the pack's detectors, in pack order, then by finding ID."""
    df = frame(snapshot, pack)
    ctx = DetectorContext(pack=pack, today=clock.today(), currency=snapshot.currency, products=products,
                          sale_lines=sale_lines, purchases=purchases, ad_spend=ad_spend)
    found: list[Finding] = []
    for cfg in pack.leak_detectors:
        spec = get_detector(cfg.detector)
        found.extend(sorted(spec.fn(df, spec.params_model.model_validate(cfg.params), ctx), key=lambda f: f.id))
    return found


def run_leak_detectors(snapshot: LedgerSnapshot, pack: Pack, clock: Clock, **pos) -> list[Fact]:
    """Every Fact of every finding (impact first, then details), for the fact store."""
    return [fact for finding in find_leaks(snapshot, pack, clock, **pos) for fact in finding.facts()]


def biggest_leak(findings: list[Finding]) -> Finding | None:
    """The finding with the largest yearly impact (ties broken by ID), for the Morning Brief."""
    return max(findings, key=lambda f: (f.impact.value, f.id), default=None)
