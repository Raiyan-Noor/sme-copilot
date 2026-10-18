"""Seed output -> real ingestion -> pack categorization -> engine, for golden tests.

Uses the same path production does: statement CSVs go through ledger.ingest into a tenant SQLite file, the
snapshot is loaded back, the pack categorizes it, and the engine computes every core fact.
"""

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import yaml

from app.clock import FixedClock
from app.engine.core import core_facts
from app.engine.pack_inputs import EnginePack, build_engine_pack
from app.firewall.fact import Fact
from app.ledger.ingest import ingest_statement
from app.ledger.pos import Product, SaleLine, load_products_csv, load_sale_lines_csv
from app.ledger.scheduled import ScheduledItem, load_scheduled_csv
from app.ledger.schema import create_tenant
from app.ledger.snapshot import LedgerSnapshot, load_snapshot
from app.packs.ledger_view import categorize_snapshot
from app.packs.loader import load_pack

GOLDEN_DIR = Path(__file__).resolve().parent
CALENDAR = GOLDEN_DIR.parents[1] / "data" / "seed" / "holidays.yaml"


@dataclass(frozen=True)
class BusinessInputs:
    snapshot: LedgerSnapshot
    pack: EnginePack
    clock: FixedClock
    scheduled: tuple[ScheduledItem, ...]
    products: tuple[Product, ...]
    sale_lines: tuple[SaleLine, ...]


def load_business(generated: Path, business_id: str, tenants: Path) -> BusinessInputs:
    biz_dir = generated / business_id
    business = json.loads((biz_dir / "business.json").read_text(encoding="utf-8"))
    conn = create_tenant(tenants / f"{business_id}.sqlite", business_id.replace("_", "-"), business["currency"],
                         pii_key=b"golden-test-fixed-key-0123456789")
    for account in business["accounts"]:
        ingest_statement(conn, (biz_dir / account["statement"]).read_bytes(),
                         source_name=account["statement"], account_number=account["account_number"],
                         account_name=account["name"])
    snapshot = load_snapshot(conn)
    conn.close()
    pack = load_pack(business["pack"])
    calendar = yaml.safe_load(CALENDAR.read_text(encoding="utf-8"))["holidays"]
    return BusinessInputs(
        snapshot=categorize_snapshot(snapshot, pack),
        pack=build_engine_pack(pack.engine_doc(), calendar),
        clock=FixedClock(date.fromisoformat(business["sim_today"])),
        scheduled=load_scheduled_csv(biz_dir / "scheduled_items.csv"),
        products=load_products_csv(biz_dir / "products.csv"),
        sale_lines=load_sale_lines_csv(biz_dir / "sale_lines.csv"),
    )


def compute(b: BusinessInputs) -> list[Fact]:
    return core_facts(b.snapshot, b.pack, b.clock, b.scheduled, b.products, b.sale_lines)
