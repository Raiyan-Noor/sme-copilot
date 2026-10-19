"""Per-product insights: best and worst margins, slow movers and stockout risk.

Pure: (products, sale lines, clock) -> (Facts, ProductInsights). Margins are the engine's existing per-product facts
(engine/margins.py, `margin.product.<id>.last_90d.margin`); this module ranks them and adds stock facts for products
whose uploaded products file has a stock count (invariant 4: `product:<id>` cites that file's row, sale lines cite
themselves). `ProductInsights` holds only fact IDs and product IDs; the brief and the UI read values from the store.

- Units sold per day over the margin window; with stock on hand that gives days of cover.
- Stockout risk: under `stockout_days` of cover while the product is still selling.
- Slow mover: stock on hand and no sale in the window, or more than `slow_days` of cover.
"""

from collections import defaultdict
from dataclasses import dataclass, field

from app.clock import Clock
from app.engine.common import count, days, slug, window
from app.firewall.fact import Fact
from app.ledger.pos import Product, SaleLine

BY = "engine.products.product_insights"
WINDOW_DAYS = 90
STOCKOUT_DAYS = 14
SLOW_DAYS = 120


@dataclass(frozen=True)
class ProductInsights:
    best_margin: str | None = None  # product ID
    worst_margin: str | None = None
    slow_movers: tuple[str, ...] = ()
    stockout_risk: tuple[str, ...] = ()
    cover_fact: dict[str, str] = field(default_factory=dict)  # product ID -> days-of-cover fact ID


def margin_fact_id(product_id: str, window_days: int = WINDOW_DAYS) -> str:
    return f"margin.product.{slug(product_id)}.last_{window_days}d.margin"


def product_facts(products: tuple[Product, ...], sale_lines: tuple[SaleLine, ...], clock: Clock,
                  window_days: int = WINDOW_DAYS, stockout_days: int = STOCKOUT_DAYS,
                  slow_days: int = SLOW_DAYS) -> tuple[list[Fact], ProductInsights]:
    if not products:
        return [], ProductInsights()
    start, end = window(clock.today(), window_days)  # the same window as engine/margins.py
    lines: dict[str, list[SaleLine]] = defaultdict(list)
    for s in sale_lines:
        if start <= s.date <= end:
            lines[s.product_id].append(s)
    margins = {}
    for p in products:
        revenue = sum(s.revenue_minor for s in lines.get(p.id, []))
        if revenue > 0:
            margins[p.id] = (revenue - sum(s.cost_minor for s in lines[p.id])) / revenue

    facts: list[Fact] = []
    cover_fact: dict[str, str] = {}
    slow, stockout = [], []
    for p in products:
        if p.stock is None:
            continue
        pre, own = f"product.{slug(p.id)}", [f"product:{p.id}"]
        ss = lines.get(p.id, [])
        units = sum(s.qty for s in ss)
        facts.append(count(f"{pre}.stock", p.stock, BY, own))
        cover_id = f"{pre}.days_of_cover"
        if p.stock > 0 and units <= 0:
            slow.append(p.id)
            facts.append(days(cover_id, None, BY, own, none_display="no sales in the last quarter"))
            cover_fact[p.id] = cover_id
            continue
        if units <= 0:
            continue
        cover = p.stock / (units / window_days)
        facts.append(days(cover_id, cover, BY, own + [s.id for s in ss], inputs=[f"{pre}.stock"]))
        cover_fact[p.id] = cover_id
        if cover < stockout_days:
            stockout.append(p.id)
        elif cover > slow_days:
            slow.append(p.id)
    if stockout:
        facts.append(count("products.stockout_risk", len(stockout), BY, [f"product:{pid}" for pid in stockout]))
    if slow:
        facts.append(count("products.slow_movers", len(slow), BY, [f"product:{pid}" for pid in slow]))
    ranked = sorted(margins, key=lambda pid: (margins[pid], pid))
    return facts, ProductInsights(
        best_margin=ranked[-1] if len(ranked) > 1 else None, worst_margin=ranked[0] if ranked else None,
        slow_movers=tuple(sorted(slow)), stockout_risk=tuple(sorted(stockout)), cover_fact=cover_fact)
