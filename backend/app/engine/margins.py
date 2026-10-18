"""Product margins from point-of-sale lines. Pure: (products, sale lines, clock) -> list[Fact].

Gross margin for the whole business is in engine/pnl.py (from the ledger). This module works per product from POS
lines, whose cost is the supplier unit cost on the day of sale, so a supplier's price creep shows up as a falling
product margin. Refunds (negative qty) reduce units, revenue and cost.
"""

from collections import defaultdict

from app.clock import Clock
from app.engine.common import a_date, count, money, ratio, slug, window
from app.firewall.fact import Fact
from app.ledger.pos import Product, SaleLine

BY = "engine.margins.product_margins"


def product_margins(products: tuple[Product, ...], sale_lines: tuple[SaleLine, ...], clock: Clock, currency: str,
                    window_days: int = 90) -> list[Fact]:
    """Per product over the last `window_days` complete days: units, revenue, cost, gross profit, margin.

    IDs like `margin.product.<product_id>.last_90d.margin`. Products with no sales in the window are skipped.
    """
    start, end = window(clock.today(), window_days)
    lines: dict[str, list[SaleLine]] = defaultdict(list)
    for s in sale_lines:
        if start <= s.date <= end:
            lines[s.product_id].append(s)
    tag = f"last_{window_days}d"
    all_ids = [s.id for ss in lines.values() for s in ss]
    facts: list[Fact] = []
    if all_ids:
        facts += [a_date(f"margin.product.{tag}.start", start, BY, all_ids),
                  a_date(f"margin.product.{tag}.end", end, BY, all_ids)]
    for p in products:
        ss = lines.get(p.id)
        if not ss:
            continue
        ids = [s.id for s in ss]
        revenue = sum(s.revenue_minor for s in ss)
        cost = sum(s.cost_minor for s in ss)
        prefix = f"margin.product.{slug(p.id)}.{tag}"
        facts += [
            count(f"{prefix}.units", sum(s.qty for s in ss), BY, ids),
            money(f"{prefix}.revenue", revenue, currency, BY, ids),
            money(f"{prefix}.cost", cost, currency, BY, ids),
            money(f"{prefix}.gross_profit", revenue - cost, currency, BY, ids,
                  inputs=[f"{prefix}.revenue", f"{prefix}.cost"]),
            ratio(f"{prefix}.margin", (revenue - cost) / revenue if revenue else None, BY, ids,
                  inputs=[f"{prefix}.revenue", f"{prefix}.gross_profit"]),
        ]
    return facts
