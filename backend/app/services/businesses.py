"""Business registry and seed bootstrap.

A business is one tenant SQLite file under data_dir. Its profile (display name, active Skill Pack, whether it is
synthetic, which seed folder it came from) is kept in the tenant's own `meta` table, so there is one source of
truth per business. Business IDs are the tenant slugs (`maya-corner-store`); seed folders use underscores.

Bootstrap loads each business in the seed output (`make seed`) through the real ingestion path: statements via
ledger.ingest (PII tokenized there), scheduled items into the tenant DB. It builds into a temporary file and
renames it into place, so a failed bootstrap never leaves a half-loaded tenant.
"""

import json
import sqlite3
from pathlib import Path

from pydantic import BaseModel

from app.audit import AuditLog
from app.ledger.ingest import ingest_statement
from app.ledger.scheduled import load_scheduled_csv
from app.ledger.schema import create_tenant, get_meta, open_tenant, tenant_path
from app.packs.loader import load_pack

META_NAME = "business_name"
META_PACK = "pack_id"
META_SYNTHETIC = "synthetic"
META_SEED = "seed_source"


class BusinessInfo(BaseModel):
    id: str
    name: str
    pack_id: str
    currency: str
    synthetic: bool
    seed_source: str | None = None


def tenant_id_for(seed_id: str) -> str:
    return seed_id.replace("_", "-")


def set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    with conn:
        conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", (key, value))


def business_info(conn: sqlite3.Connection) -> BusinessInfo:
    business_id = get_meta(conn, "business_id") or ""
    return BusinessInfo(
        id=business_id,
        name=get_meta(conn, META_NAME) or business_id,
        pack_id=get_meta(conn, META_PACK) or "",
        currency=get_meta(conn, "currency") or "",
        synthetic=get_meta(conn, META_SYNTHETIC) == "true",
        seed_source=get_meta(conn, META_SEED),
    )


def list_businesses(data_dir: Path) -> list[BusinessInfo]:
    found = []
    for path in sorted(data_dir.glob("*.sqlite")):
        conn = open_tenant(path)
        try:
            found.append(business_info(conn))
        finally:
            conn.close()
    return found


def set_pack(conn: sqlite3.Connection, pack_id: str) -> None:
    """Switch the active Skill Pack. Raises PackError for an unknown pack (only bundled packs resolve)."""
    load_pack(pack_id)
    set_meta(conn, META_PACK, pack_id)


def seed_profiles(seed_dir: Path) -> list[dict]:
    """Every business.json in the seed output, sorted by ID."""
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(seed_dir.glob("*/business.json"))]


def bootstrap_from_seed(seed_dir: Path, data_dir: Path, audit: AuditLog) -> list[str]:
    """Create a tenant for each seed business that does not have one yet. Returns the IDs created."""
    created = []
    for profile in seed_profiles(seed_dir):
        business_id = tenant_id_for(profile["id"])
        path = tenant_path(data_dir, business_id)
        if path.exists():
            continue
        tmp = path.with_suffix(".sqlite.tmp")
        tmp.unlink(missing_ok=True)
        counts = _load_seed_business(seed_dir / profile["id"], profile, business_id, tmp)
        tmp.replace(path)
        created.append(business_id)
        audit.append("ledger.tenant_seeded", {"business_id": business_id, "pack_id": profile["pack"],
                                              "synthetic": bool(profile.get("synthetic")), **counts})
    return created


def _load_seed_business(biz_dir: Path, profile: dict, business_id: str, path: Path) -> dict:
    conn = create_tenant(path, business_id, profile["currency"])
    try:
        set_meta(conn, META_NAME, profile["name"])
        set_meta(conn, META_PACK, load_pack(profile["pack"]).id)
        set_meta(conn, META_SYNTHETIC, "true" if profile.get("synthetic") else "false")
        set_meta(conn, META_SEED, profile["id"])
        inserted = 0
        for account in profile["accounts"]:
            report = ingest_statement(conn, (biz_dir / account["statement"]).read_bytes(),
                                      source_name=Path(account["statement"]).name,
                                      account_number=account["account_number"], account_name=account["name"])
            inserted += report.inserted
        items = load_scheduled_csv(biz_dir / "scheduled_items.csv")
        with conn:
            conn.executemany(
                "INSERT INTO scheduled_items (id, kind, category, due_date, amount_minor, status, counterparty_id,"
                " reference, source) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [(s.id, s.kind, s.category, s.due_date.isoformat(), s.amount_minor, s.status, s.counterparty_id,
                  s.reference, s.source) for s in items],
            )
        return {"accounts": len(profile["accounts"]), "transactions": inserted, "scheduled_items": len(items)}
    finally:
        conn.close()


def open_business(data_dir: Path, business_id: str) -> sqlite3.Connection:
    """Open a tenant by ID. Raises TenantError for a bad or unknown ID."""
    return open_tenant(tenant_path(data_dir, business_id))
