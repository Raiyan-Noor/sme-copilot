"""Audit log: read, verify and export the hash-chained log (invariant 7). Read-only; nothing here appends except
the record that an export happened and the record of an on-chain check.

Verify runs two checks. Locally, every hash and link is recomputed from the file; that alone cannot catch an insider
who rewrites the file and recomputes every hash. So it also recomputes each anchored batch's root from the log and
compares it with the root fetched from the testnet transaction (invariant 9)."""

from typing import Annotated

from fastapi import APIRouter, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.anchoring.service import LogAnchorCheck
from app.api.deps import RuntimeDep
from app.audit import AuditEntry, Head, VerifyResult

router = APIRouter(tags=["audit"])


class AuditPage(BaseModel):
    head: Head
    total: int
    offset: int
    limit: int
    entries: list[AuditEntry]  # newest first


@router.get("/audit", response_model=AuditPage)
def get_audit(
    rt: RuntimeDep,
    kind: Annotated[str | None, Query(max_length=64, description="exact kind, or a prefix ending in '.'")] = None,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> AuditPage:
    entries = rt.audit.entries()
    if kind:
        entries = [e for e in entries if e.kind == kind or (kind.endswith(".") and e.kind.startswith(kind))]
    entries.reverse()
    return AuditPage(head=rt.audit.head(), total=len(entries), offset=offset, limit=limit,
                     entries=entries[offset:offset + limit])


@router.get("/audit/head", response_model=Head)
def get_head(rt: RuntimeDep) -> Head:
    """The chain head: what on-chain anchoring publishes."""
    return rt.audit.head()


class AuditVerifyResult(VerifyResult):
    onchain: LogAnchorCheck


@router.get("/audit/verify", response_model=AuditVerifyResult)
def verify(rt: RuntimeDep) -> AuditVerifyResult:
    """Recompute every hash and link (the first entry that breaks the chain is reported), then check the log against
    every anchored root on chain: `onchain.ok` is false if any batch mismatches, null if nothing is anchored yet."""
    local = rt.audit.verify()
    return AuditVerifyResult(**local.model_dump(), onchain=rt.anchors.verify_log())


@router.get("/audit/export", response_class=FileResponse,
            responses={200: {"content": {"application/x-ndjson": {}}, "description": "The audit log as JSONL"}})
def export(rt: RuntimeDep) -> FileResponse:
    """Download a verified copy of the log. `X-Audit-Verified` and `X-Audit-Head-*` describe the exported file."""
    head = rt.audit.head()
    dest = rt.data_dir / "exports" / f"audit-{head.seq + 1:06d}-{head.hash[:12]}.jsonl"
    result = rt.audit.export(dest)
    rt.audit.append("audit.exported", {"entries": result.entries, "head_seq": result.head.seq,
                                       "head_hash": result.head.hash, "verified": result.ok})
    return FileResponse(dest, media_type="application/x-ndjson", filename=dest.name, headers={
        "X-Audit-Verified": "true" if result.ok else "false",
        "X-Audit-Head-Seq": str(result.head.seq),
        "X-Audit-Head-Hash": result.head.hash,
    })
