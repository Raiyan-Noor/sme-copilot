"""All core finance facts for one business in one call: P&L, margins, cash, buffer days, forecast, runway.

Pure, like every calculator it calls. The snapshot must already be categorized by the active pack
(packs.ledger_view.categorize_snapshot), and `pack` is that pack's EnginePack view.
"""

from app.clock import Clock
from app.engine.cash import buffer_days, cash_balance
from app.engine.forecast import forecast, runway
from app.engine.margins import product_margins
from app.engine.pack_inputs import EnginePack
from app.engine.pnl import gross_margin, pnl_by_period
from app.firewall.fact import Fact
from app.ledger.pos import Product, SaleLine
from app.ledger.scheduled import ScheduledItem
from app.ledger.snapshot import LedgerSnapshot


def core_facts(snapshot: LedgerSnapshot, pack: EnginePack, clock: Clock,
               scheduled: tuple[ScheduledItem, ...] = (), products: tuple[Product, ...] = (),
               sale_lines: tuple[SaleLine, ...] = ()) -> list[Fact]:
    """Every core fact once, in a stable order. Facts several calculators share (cash.balance) are emitted once."""
    groups = [
        cash_balance(snapshot, clock),
        buffer_days(snapshot, pack, clock),
        pnl_by_period(snapshot, pack, clock),
        gross_margin(snapshot, pack, clock),
        product_margins(products, sale_lines, clock, snapshot.currency),
        forecast(snapshot, pack, clock, scheduled),
        runway(snapshot, pack, clock, scheduled),
    ]
    seen: dict[str, Fact] = {}
    for fact in (f for g in groups for f in g):
        prior = seen.setdefault(fact.id, fact)
        if prior != fact:
            raise ValueError(f"two calculators disagree on {fact.id}")
    return list(seen.values())
