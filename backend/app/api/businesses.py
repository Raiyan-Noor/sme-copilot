"""Businesses and the Skill Pack switch."""

from fastapi import APIRouter
from pydantic import BaseModel

from app.api.deps import BusinessId, RuntimeDep
from app.packs.loader import list_pack_ids, load_pack
from app.services.businesses import BusinessInfo, business_info, list_businesses, set_pack

router = APIRouter(tags=["businesses"])


class Account(BaseModel):
    id: str  # PII token of the account number, or book_<name> for an internal book
    name: str
    currency: str


class BusinessDetail(BusinessInfo):
    accounts: list[Account]
    transactions: int
    scheduled_items: int


class PackSummary(BaseModel):
    id: str
    version: int
    ref: str
    display_name: str
    benchmarks_synthetic: bool


class PackSwitch(BaseModel):
    pack_id: str


@router.get("/businesses", response_model=list[BusinessInfo])
def get_businesses(rt: RuntimeDep) -> list[BusinessInfo]:
    rt.ensure_ready()
    return list_businesses(rt.data_dir)


@router.get("/businesses/{business_id}", response_model=BusinessDetail)
def get_business(business_id: BusinessId, rt: RuntimeDep) -> BusinessDetail:
    with rt.business(business_id) as conn:
        accounts = [Account(**dict(r)) for r in conn.execute("SELECT id, name, currency FROM accounts ORDER BY id")]
        n_txn = conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
        n_sched = conn.execute("SELECT COUNT(*) FROM scheduled_items").fetchone()[0]
        return BusinessDetail(**business_info(conn).model_dump(), accounts=accounts, transactions=n_txn,
                              scheduled_items=n_sched)


@router.get("/packs", response_model=list[PackSummary])
def get_packs() -> list[PackSummary]:
    packs = [load_pack(pid) for pid in list_pack_ids()]
    return [PackSummary(id=p.id, version=p.version, ref=p.ref, display_name=p.display_name,
                        benchmarks_synthetic=p.benchmarks_synthetic) for p in packs]


@router.put("/businesses/{business_id}/pack", response_model=BusinessInfo)
def switch_pack(business_id: BusinessId, body: PackSwitch, rt: RuntimeDep) -> BusinessInfo:
    """Switch the business's active Skill Pack. Categories, forecast seasonality and KPIs follow it."""
    with rt.business(business_id) as conn:
        before = business_info(conn).pack_id
        set_pack(conn, body.pack_id)
        info = business_info(conn)
    rt.audit.append("business.pack_switched", {"business_id": business_id, "from": before, "to": info.pack_id})
    return info
