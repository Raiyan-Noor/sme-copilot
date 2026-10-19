"""One business's engine inputs and the full set of Facts computed from them (invariant 4).

`load_inputs` reads the tenant DB (ledger rows, scheduled items) and the business's own records (point-of-sale, purchase
and ad spend files from its seed or onboarding records folder), applies the owner's onboarding answers to the active
Skill Pack (packs/answers.py) and categorizes the ledger with it. `compute` runs every calculator once and returns a
FactStore, so every number the API returns can be traced with explain_fact in the same request.
"""

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path

import yaml

from app.clock import Clock
from app.engine.ads import AdInsights, ad_facts
from app.engine.common import today_fact
from app.engine.core import core_facts
from app.engine.pack_inputs import EnginePack, build_engine_pack
from app.engine.pnl import pnl_by_period
from app.engine.products import ProductInsights, product_facts
from app.engine.scheduled import scheduled_item_facts
from app.firewall.explain import Resolver, SourceRow
from app.firewall.store import FactStore
from app.ledger.documents import Receivable, load_receivables_csv, supplier_invoices
from app.ledger.pos import Product, SaleLine, load_products_csv, load_sale_lines_csv
from app.ledger.purchases import PurchaseLine, load_purchases_csv
from app.ledger.records import AdSpendLine, load_ad_spend_csv
from app.ledger.scheduled import ScheduledItem, load_scheduled
from app.ledger.schema import get_meta
from app.ledger.snapshot import LedgerSnapshot, load_snapshot
from app.firewall.fact import Fact
from app.packs.answers import effective_pack
from app.packs.benchmarks import Benchmark, benchmark, compute_kpis
from app.packs.leaks import find_leaks
from app.packs.ledger_view import categorize_snapshot
from app.packs.loader import load_pack
from app.packs.registry import Finding
from app.packs.schema import Pack
from app.services.businesses import BusinessInfo, advisor_answers, business_info, records_folder
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
    ad_spend: tuple[AdSpendLine, ...] = ()  # campaign spend export, for return on ad spend
    owner_facts: tuple[Fact, ...] = ()  # answers the owner gave at onboarding (packs/answers.py)
    records: Path | None = None  # the business's own records folder (seed or onboarding)


@dataclass(frozen=True)
class Computed:
    inputs: BusinessInputs
    store: FactStore
    benchmarks: tuple[Benchmark, ...]
    facts_sha256: str
    leaks: tuple[Finding, ...] = ()  # every leak finding; its facts are in `store`
    financing: FinancingResult | None = None  # financing match and Readiness Passport; facts are in `store`
    products: ProductInsights = ProductInsights()
    ads: AdInsights = AdInsights()


def ledger_version(conn: sqlite3.Connection) -> tuple[int, ...]:
    """Changes whenever rows are added: part of the cache key for computed facts."""
    row = conn.execute(
        "SELECT (SELECT COUNT(*) FROM transactions), (SELECT COUNT(*) FROM imports),"
        " (SELECT COUNT(*) FROM scheduled_items)"
    ).fetchone()
    return tuple(row)


def records_version(conn: sqlite3.Connection, seed_dir: Path) -> tuple:
    """Changes when the business's own records files change (onboarding uploads, answers): part of the cache key."""
    folder = records_folder(conn, seed_dir)
    files = sorted(folder.glob("*")) if folder and folder.is_dir() else []
    return (get_meta(conn, "advisor_answers"), *((f.name, f.stat().st_mtime_ns, f.stat().st_size) for f in files))


def load_inputs(conn: sqlite3.Connection, seed_dir: Path, holiday_calendar: Path) -> BusinessInputs:
    info = business_info(conn)
    pack, owner_facts = effective_pack(load_pack(info.pack_id), advisor_answers(conn))
    calendar = yaml.safe_load(holiday_calendar.read_text(encoding="utf-8"))["holidays"]
    products: tuple[Product, ...] = ()
    sale_lines: tuple[SaleLine, ...] = ()
    pos_dir = records_folder(conn, seed_dir)
    if pos_dir and (pos_dir / "products.csv").exists():
        products = load_products_csv(pos_dir / "products.csv")
    if pos_dir and products and (pos_dir / "sale_lines.csv").exists():
        sale_lines = load_sale_lines_csv(pos_dir / "sale_lines.csv")
    purchases: tuple[PurchaseLine, ...] = ()
    if pos_dir and (pos_dir / "purchases.csv").exists():
        purchases = load_purchases_csv(pos_dir / "purchases.csv")
    receivables: tuple[Receivable, ...] = ()
    if pos_dir and (pos_dir / "receivables.csv").exists():
        receivables = load_receivables_csv(pos_dir / "receivables.csv")
    ad_spend = load_ad_spend_csv(pos_dir / "ad_spend.csv") if pos_dir else ()
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
        ad_spend=ad_spend,
        owner_facts=tuple(owner_facts),
        records=pos_dir,
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
                       sale_lines=inputs.sale_lines, purchases=inputs.purchases, ad_spend=inputs.ad_spend)
    store.add_all(fact for finding in leaks for fact in finding.facts())
    product_extra, product_insights = product_facts(inputs.products, inputs.sale_lines, clock)
    store.add_all(product_extra)
    ad_extra, ad_insights = ad_facts(inputs.ad_spend, clock, inputs.snapshot.currency)
    store.add_all(ad_extra)
    store.add_all(inputs.owner_facts)
    financing = financing_facts(
        store=store, snapshot=inputs.snapshot, pack=inputs.pack, clock=clock, receivables=inputs.receivables,
        supplier_invoices=supplier_invoices(inputs.purchases), business_id=inputs.info.id,
        business_name=inputs.info.name, synthetic_data=inputs.info.synthetic)
    dump = sorted((f.model_dump(mode="json") for f in store), key=lambda d: d["id"])
    digest = hashlib.sha256(json.dumps(dump, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return Computed(inputs=inputs, store=store, benchmarks=tuple(benchmarks), facts_sha256=digest,
                    leaks=tuple(leaks), financing=financing, products=product_insights, ads=ad_insights)


def resolver(inputs: BusinessInputs) -> Resolver:
    """Look up a cited source ID among this business's transactions, scheduled items and sale lines."""
    txns = inputs.snapshot.by_id()
    scheduled = {s.id: s for s in inputs.scheduled}
    sales = {s.id: s for s in inputs.sale_lines}
    purchases = {p.id: p for p in inputs.purchases}
    receivables = {r.id: r for r in inputs.receivables}
    invoices = {i.id: i for i in supplier_invoices(inputs.purchases)}
    products = {f"product:{p.id}": p for p in inputs.products}
    ads = {a.id: a for a in inputs.ad_spend}
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
        if (p := products.get(ref)) is not None:
            return SourceRow(id=ref, kind="product", amount_minor=p.price_minor, currency=currency,
                             category=p.category, text=f"{p.name}: stock {p.stock} (products file)")
        if (a := ads.get(ref)) is not None:
            return SourceRow(id=a.id, kind="ad_spend", date=a.date, amount_minor=-a.spend_minor, currency=currency,
                             category=a.channel, text=f"{a.campaign} (ad spend export)")
        return None

    return resolve
