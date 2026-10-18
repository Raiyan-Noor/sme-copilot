"""Gateway routes: owner key enrolment, approvals signed by the owner, standing mandates, and (testing only) a
direct propose route.

Invariant 6: the server never sees a private key. The browser (or `scripts/sign_payload.py` when testing from
/docs) signs the canonical `message` of a payload with tweetnacl/PyNaCl and sends only the signature and public key.
Invariant 1: these routes call the Gateway, never an executor. The propose route goes through exactly the same
policy checks as the planner's propose_action; it exists so the gateway can be exercised from /docs.

Owner keys are enrolled trust-on-first-use: the first key for a business is accepted, any other key afterwards is
refused, so holding the passcode is not enough to add a second signer.
"""

import secrets
from datetime import timedelta
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Path
from pydantic import BaseModel, Field

from app.api.deps import BusinessId, RuntimeDep
from app.gateway import Decision, MandateResult, ProposedAction, SignedPayload, StandingTerms

router = APIRouter(tags=["gateway"])
test_router = APIRouter(tags=["gateway (testing)"])

PublicKeyHex = Annotated[str, Field(pattern=r"^[0-9a-fA-F]{64}$", description="Ed25519 public key, hex")]
SignatureHex = Annotated[str, Field(pattern=r"^[0-9a-fA-F]{128}$", description="Ed25519 signature, hex")]
ApprovalId = Annotated[str, Path(pattern=r"^apr_[0-9a-f]{16}$")]


class OwnerKeyRequest(BaseModel):
    public_key: PublicKeyHex


class OwnerKey(BaseModel):
    public_key: str
    enrolled: bool


class ApprovalView(BaseModel):
    """A pending (or decided) approval. The owner signs `message`: the canonical JSON bytes of `payload`."""

    approval_id: str
    tool: str
    status: str
    args: dict[str, Any]
    reasons: list[str]
    payload: SignedPayload
    message: str
    requires_out_of_band_call_script: bool


class ApproveRequest(BaseModel):
    signature: SignatureHex
    public_key: PublicKeyHex
    out_of_band_confirmed: bool = False


class StandingMandateDraftRequest(BaseModel):
    action: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    terms: StandingTerms
    days: int = Field(default=30, ge=1, le=365)


class StandingMandateDraft(BaseModel):
    """A payload for the owner to sign: `args_hash` binds the terms, the nonce is fresh, `message` is what to sign."""

    payload: SignedPayload
    terms: StandingTerms
    message: str


class StandingMandateRequest(BaseModel):
    payload: SignedPayload
    terms: StandingTerms
    signature: SignatureHex
    public_key: PublicKeyHex


@router.post("/businesses/{business_id}/gateway/owner-key", response_model=OwnerKey)
def enroll_owner_key(business_id: BusinessId, body: OwnerKeyRequest, rt: RuntimeDep) -> OwnerKey:
    """Enroll the owner's public key (first key only; re-sending the same key is a no-op)."""
    gw = rt.gateway(business_id)
    key = body.public_key.lower()
    if gw.store.is_enrolled(key):
        return OwnerKey(public_key=key, enrolled=True)
    if gw.store.has_owner_key():
        rt.audit.append("gateway.key_rejected", {"business_id": business_id, "public_key": key,
                                                 "rule": "owner_key_already_enrolled"})
        raise HTTPException(409, "an owner key is already enrolled for this business")
    gw.enroll_owner_key(key)
    return OwnerKey(public_key=key, enrolled=True)


@router.get("/businesses/{business_id}/gateway/approvals/{approval_id}", response_model=ApprovalView)
def get_approval(business_id: BusinessId, approval_id: ApprovalId, rt: RuntimeDep) -> ApprovalView:
    gw = rt.gateway(business_id)
    approval = gw.store.get_approval(approval_id)
    if approval is None:
        raise HTTPException(404, "no such approval")
    t3 = gw.policy.t3.get(approval.tool)
    return ApprovalView(approval_id=approval.id, tool=approval.tool, status=approval.status, args=approval.args,
                        reasons=approval.reasons, payload=approval.payload,
                        message=approval.payload.message().decode(),
                        requires_out_of_band_call_script=bool(t3 and t3.requires_out_of_band_call_script))


@router.post("/businesses/{business_id}/gateway/approvals/{approval_id}/approve", response_model=Decision)
def approve(business_id: BusinessId, approval_id: ApprovalId, body: ApproveRequest, rt: RuntimeDep) -> Decision:
    """Execute a pending action with the owner's signature over its exact payload. Returns the gateway's decision:
    `executed`, or `denied` with the rule that fired (bad signature, expired, replayed nonce, ...)."""
    return rt.gateway(business_id).approve(approval_id, body.signature.lower(), body.public_key.lower(),
                                           out_of_band_confirmed=body.out_of_band_confirmed)


@router.post("/businesses/{business_id}/gateway/mandates/draft", response_model=StandingMandateDraft)
def draft_standing_mandate(business_id: BusinessId, body: StandingMandateDraftRequest,
                           rt: RuntimeDep) -> StandingMandateDraft:
    """Build the payload for a T2 standing mandate. Nothing is stored; the gateway checks it when registered."""
    rt.gateway(business_id)
    payload = SignedPayload(action=body.action, args_hash=body.terms.hash(), nonce=secrets.token_hex(16),
                            expiry=rt.clock.today() + timedelta(days=body.days))
    return StandingMandateDraft(payload=payload, terms=body.terms, message=payload.message().decode())


@router.post("/businesses/{business_id}/gateway/mandates", response_model=MandateResult)
def register_standing_mandate(business_id: BusinessId, body: StandingMandateRequest,
                              rt: RuntimeDep) -> MandateResult:
    """Register a signed T2 standing mandate. Its terms may lower policy caps but never raise them."""
    return rt.gateway(business_id).register_standing_mandate(body.payload, body.terms, body.signature.lower(),
                                                             body.public_key.lower())


@test_router.post("/businesses/{business_id}/gateway/propose", response_model=Decision)
def propose(business_id: BusinessId, body: ProposedAction, rt: RuntimeDep) -> Decision:
    """Testing: propose an action as the planner would. Returns `executed`, `pending_approval` or `denied`."""
    return rt.gateway(business_id).propose(body)
