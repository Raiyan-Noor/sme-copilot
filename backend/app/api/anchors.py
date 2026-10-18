"""On-chain anchoring routes (invariant 9): status and batches, "Anchor now", and on-chain verification of signed
mandates, exported Passports and any Passport file a third party holds.

Thin: every check is in app/anchoring. Hashes are always recomputed here from the stored document (mandate row,
Passport file, uploaded Passport), never taken from the record of what was signed, so an edit after anchoring is
reported as a mismatch. The audit log's on-chain check is part of GET /audit/verify.
"""

import json
from typing import Annotated, Any

from fastapi import APIRouter, Body, HTTPException, Path

from app.anchoring.service import AnchorRequestResult, AnchorStatus, LeafCheck
from app.api.deps import BusinessId, RuntimeDep
from app.audit.canonical import CanonicalError, canonical_hash, sha256_hex
from app.services.financing import verify_passport_bytes

router = APIRouter(tags=["anchoring"])

Sha256 = Annotated[str, Path(pattern=r"^[0-9a-f]{64}$")]
MandateId = Annotated[int, Path(ge=1)]


@router.get("/anchors", response_model=AnchorStatus)
def get_anchors(rt: RuntimeDep) -> AnchorStatus:
    """Whether a testnet is configured, and every batch (newest first) with its root, leaves, proofs and tx."""
    return rt.anchors.status()


@router.post("/anchors", response_model=AnchorRequestResult)
def anchor_now(rt: RuntimeDep) -> AnchorRequestResult:
    """Cut a batch now and publish its root in the background. Rate-capped by policy.yaml; testnet only."""
    return rt.anchors.request("manual", manual=True)


@router.get("/businesses/{business_id}/gateway/mandates/{mandate_id}/onchain", response_model=LeafCheck)
def verify_mandate_onchain(business_id: BusinessId, mandate_id: MandateId, rt: RuntimeDep) -> LeafCheck:
    """Recompute the mandate's hash from its stored document, find it in an anchored batch, fold its proof into a
    root and compare that root with the transaction on chain."""
    stored = rt.gateway(business_id).store.mandate_document(mandate_id)
    if stored is None:
        raise HTTPException(404, "no such mandate")
    document, recorded = stored
    try:
        recomputed = canonical_hash(document)
    except CanonicalError:
        recomputed = sha256_hex(json.dumps(document, sort_keys=True).encode())
    return rt.anchors.verify_leaf("mandate", recomputed, recorded)


@router.get("/businesses/{business_id}/passport/exports/{sha256}/onchain", response_model=LeafCheck)
def verify_passport_export_onchain(business_id: BusinessId, sha256: Sha256, rt: RuntimeDep) -> LeafCheck:
    """Re-hash the exported Passport file as it is on disk now and check that hash on chain."""
    with rt.business(business_id):
        pass
    path = rt.data_dir / business_id / "passports" / f"{sha256}.json"
    if not path.is_file():
        raise HTTPException(404, "no export with this hash")
    try:
        recomputed = verify_passport_bytes(path.read_bytes())
    except (ValueError, CanonicalError):
        recomputed = sha256_hex(path.read_bytes())
    return rt.anchors.verify_leaf("passport", recomputed, sha256)


@router.post("/anchors/verify/passport", response_model=LeafCheck)
def verify_passport_file(rt: RuntimeDep, passport: Annotated[dict[str, Any], Body(
        description="An exported Passport file, as JSON. It is hashed as canonical JSON.")]) -> LeafCheck:
    """For a lender or any holder of a Passport file: hash it canonically and report whether that hash is an
    anchored leaf whose root is on chain. Nothing about the file is stored."""
    try:
        digest = canonical_hash(passport)
    except CanonicalError as exc:
        raise HTTPException(422, f"not a canonical Passport: {exc}") from None
    return rt.anchors.verify_leaf("passport", digest)
