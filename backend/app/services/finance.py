"""One business's engine inputs and the full set of Facts computed from them (invariant 4).

`load_inputs` reads the tenant DB (ledger rows, scheduled items) and the seed's point-of-sale files, and
categorizes the ledger with the business's active Skill Pack. `compute` runs every calculator once and returns a
FactStore, so every number the API returns can be traced with explain_fact in the same request.
"""

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path

import yaml

from app.clock import Clock
from app.engine.common import today_fact
from app.engine.core import core_facts
from app.engine.pack_inputs import EnginePack, build_engine_pack
from app.engine.pnl import pnl_by_period
from app.engine.scheduled import scheduled_item_facts
from app.firewall.explain import Resolver, SourceRow
from app.firewall.store import FactStore
from app.ledger.documents import Receivable, load_receivables_csv, supplier_invoices
from app.ledger.pos import Product, SaleLine, load_products_csv, load_sale_lines_csv
from app.ledger.purchases import PurchaseLine, load_purchases_csv
from app.ledger.scheduled import ScheduledItem, load_scheduled
from app.ledger.snapshot import LedgerSnapshot, load_snapshot
from app.packs.benchmarks import Benchmark, benchmark, compute_kpis
from app.packs.leaks import find_leaks
from app.packs.ledger_view import categorize_snapshot
from app.packs.loader import load_pack
from app.packs.registry import Finding
from app.packs.schema import Pack
from app.services.businesses import BusinessInfo, business_info
from app.services.financing import FinancingResult, financing_facts


@dataclass(frozen=True)
class BusinessInputs:
    info: BusinessInfo
    pack: Pack
    engine_pack: EnginePack
    snapshot: LedgerSnapshot  # categorized by the active pack
    scheduled: tuple[ScheduledItem, ...]
    products: tuple[Product, ...]
    sale_lines: tuple[SaleLine, ...]
    purchases: tuple[PurchaseLine, ...] = ()  # supplier invoice lines, for the purchase-based leak detectors
    receivables: tuple[Receivable, ...] = ()  # customer invoices issued, for the Readiness Passport


@dataclass(frozen=True)
class Computed:
    inputs: BusinessInputs
    store: FactStore
    benchmarks: tuple[Benchmark, ...]
    facts_sha256: str
    leaks: tuple[Finding, ...] = ()  # every leak finding; its facts are in `store`
    financing: FinancingResult | None = None  # financing match and Readiness Passport; facts are in `store`


def ledger_version(conn: sqlite3.Connection) -> tuple[int, ...]:
    """Changes whenever rows are added: part of the cache key for computed facts."""
    row = conn.execute(
        "SELECT (SELECT COUNT(*) FROM transactions), (SELECT COUNT(*) FROM imports),"
        " (SELECT COUNT(*) FROM scheduled_items)"
    ).fetchone()
    return tuple(row)


def load_inputs(conn: sqlite3.Connection, seed_dir: Path, holiday_calendar: Path) -> BusinessInputs:
    info = business_info(conn)
    pack = load_pack(info.pack_id)
    calendar = yaml.safe_load(holiday_calendar.read_text(encoding="utf-8"))["holidays"]
    products: tuple[Product, ...] = ()
    sale_lines: tuple[SaleLine, ...] = ()
    pos_dir = seed_dir / info.seed_source if info.seed_source else None
    if pos_dir and (pos_dir / "products.csv").exists() and (pos_dir / "sale_lines.csv").exists():
        products = load_products_csv(pos_dir / "products.csv")
        sale_lines = load_sale_lines_csv(pos_dir / "sale_lines.csv")
    purchases: tuple[PurchaseLine, ...] = ()
    if pos_dir and (pos_dir / "purchases.csv").exists():
        purchases = load_purchases_csv(pos_dir / "purchases.csv")
    receivables: tuple[Receivable, ...] = ()
    if pos_dir and (pos_dir / "receivables.csv").exists():
        receivables = load_receivables_csv(pos_dir / "receivables.csv")
    return BusinessInputs(
        info=info,
        pack=pack,
        engine_pack=build_engine_pack(pack.engine_doc(), calendar),
        snapshot=categorize_snapshot(load_snapshot(conn), pack),
        scheduled=load_scheduled(conn),
        products=products,
        sale_lines=sale_lines,
        purchases=purchases,
        receivables=receivables,
    )


def compute(inputs: BusinessInputs, clock: Clock) -> Computed:
    """Core engine facts, weekly P&L, pack KPIs, benchmark bounds, open scheduled items, leak findings and the
    simulated date, all in one store: the planner's tools and the owner's explain_fact read the same facts."""
    store = FactStore()
    store.add(today_fact(clock.today(), "services.finance.compute"))
    facts = core_facts(inputs.snapshot, inputs.engine_pack, clock, inputs.scheduled, inputs.products,
                       inputs.sale_lines)
    store.add_all(facts)
    store.add_all(pnl_by_period(inputs.snapshot, inputs.engine_pack, clock, period="week"))
    kpis = compute_kpis(inputs.snapshot, inputs.pack, clock)
    store.add_all(kpis)
    engine_kpis = {"buffer_days": store.get("cash.buffer_days")}
    benchmarks, bounds = benchmark({**{f.id: f for f in kpis}, **engine_kpis}, inputs.pack)
    store.add_all(bounds)
    store.add_all(scheduled_item_facts(inputs.scheduled, clock, inputs.snapshot.currency))
    leaks = find_leaks(inputs.snapshot, inputs.pack, clock, products=inputs.products,
                       sale_lines=inputs.sale_lines, purchases=inputs.purchases)
    store.add_all(fact for finding in leaks for fact in finding.facts())
    financing = financing_facts(
        store=store, snapshot=inputs.snapshot, pack=inputs.pack, clock=clock, receivables=inputs.receivables,
        supplier_invoices=supplier_invoices(inputs.purchases), business_id=inputs.info.id,
        business_name=inputs.info.name, synthetic_data=inputs.info.synthetic)
    dump = sorted((f.model_dump(mode="json") for f in store), key=lambda d: d["id"])
    digest = hashlib.sha256(json.dumps(dump, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return Computed(inputs=inputs, store=store, benchmarks=tuple(benchmarks), facts_sha256=digest,
                    leaks=tuple(leaks), financing=financing)


def resolver(inputs: BusinessInputs) -> Resolver:
    """Look up a cited source ID among this business's transactions, scheduled items and sale lines."""
    txns = inputs.snapshot.by_id()
    scheduled = {s.id: s for s in inputs.scheduled}
    sales = {s.id: s for s in inputs.sale_lines}
    purchases = {p.id: p for p in inputs.purchases}
    receivables = {r.id: r for r in inputs.receivables}
    invoices = {i.id: i for i in supplier_invoices(inputs.purchases)}
    currency = inputs.snapshot.currency

    def resolve(ref: str) -> SourceRow | None:
        if (t := txns.get(ref)) is not None:
            return SourceRow(id=t.id, kind="transaction", date=t.posted_on, amount_minor=t.amount_minor,
                             currency=t.currency, category=t.category, account_id=t.account_id, text=t.description)
        if (s := scheduled.get(ref)) is not None:
            return SourceRow(id=s.id, kind="scheduled_item", date=s.due_date, amount_minor=s.signed_minor,
                             currency=currency, category=s.category, text=s.reference)
        if (line := sales.get(ref)) is not None:
            return SourceRow(id=line.id, kind="sale_line", date=line.date, amount_minor=line.revenue_minor,
                             currency=currency, category=line.product_id)
        if (buy := purchases.get(ref)) is not None:
            return SourceRow(id=buy.id, kind="purchase_line", date=buy.invoice_date,
                             amount_minor=-buy.line_total_minor, currency=currency, category=buy.product_id,
                             text=f"{buy.invoice_id} {buy.supplier_id} x{buy.qty}")
        if (rec := receivables.get(ref)) is not None:
            paid = f", paid {rec.paid_on.isoformat()}" if rec.paid_on else ", unpaid"
            return SourceRow(id=rec.id, kind="receivable", date=rec.issue_date, amount_minor=rec.amount_minor,
                             currency=currency, category=rec.customer_id,
                             text=f"due {rec.due_date.isoformat()}{paid}")
        if (inv := invoices.get(ref)) is not None:
            paid = f", paid {inv.paid_on.isoformat()}" if inv.paid_on else ", unpaid"
            return SourceRow(id=inv.id, kind="supplier_invoice", date=inv.invoice_date,
                             amount_minor=-inv.amount_minor, currency=currency, category=inv.supplier_id,
                             text=f"due {inv.due_date.isoformat()}{paid}")
        return None

    return resolve
