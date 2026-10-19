"""Payments tab: the SandboxPay connection, payees, pay requests and their live status, receipts and on-chain checks.

Thin routes over services/payments.py, where every step is audited. Two routes are public, because the provider
calls them without the passcode: the consent callback (acts only on a one-time state this server issued) and the
settlement webhook (acts only when its HMAC verifies with the connection's secret). Approving a payment uses the
existing gateway route (`/gateway/approvals/{id}/approve`): the owner signs in the browser (invariant 6).
"""

import html
import json
from typing import Annotated

from fastapi import APIRouter, Header, Path, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field

from app.anchoring.service import LeafCheck
from app.api.deps import BusinessId, RuntimeDep
from app.audit.canonical import CanonicalError, canonical_hash
from app.services.payments import (
    PaymentConnectionStatus, PaymentsError, PaymentsOverview, PaymentView, Payee,
)
from app.services.payment_store import PaymentStatus

router = APIRouter(tags=["payments"])

CALLBACK_PATH = "/payments/sandboxpay/callback"
WEBHOOK_PREFIX = "/payments/sandboxpay/webhook/"
RequestId = Annotated[str, Path(pattern=r"^pr_[0-9a-f]{16}$")]


class PaymentConnectStart(BaseModel):
    authorize_url: str


class PaymentConnectRequest(BaseModel):
    client_name: str = Field(default="", max_length=60, description="The app's display name for the consent screen")


class PaymentCreate(BaseModel):
    """Either `source` (a suggestion's key: payee and amount come from the business's records) or a manual request
    (`payee_id` + `amount_minor`)."""

    source: str | None = Field(default=None, max_length=80, pattern=r"^(item|email):[A-Za-z0-9_\-]{1,64}$")
    payee_id: str | None = Field(default=None, max_length=64)
    amount_minor: int | None = Field(default=None, gt=0, le=10**12)
    reason: str = Field(default="", max_length=200)
    reference: str | None = Field(default=None, max_length=64)


class PayeeCreate(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    account_number: str = Field(min_length=6, max_length=40)
    confirm_account_number: str = Field(min_length=6, max_length=40)
    confirmed: bool = False


class CallVerification(BaseModel):
    email_id: str = Field(pattern=r"^(em|up|gm|dc)-[a-z0-9]{3,16}$")


class Receipt(BaseModel):
    request_id: str
    receipt_sha256: str
    document: dict


class WebhookResult(BaseModel):
    accepted: bool
    outcome: str


@router.get("/businesses/{business_id}/payments", response_model=PaymentsOverview)
def payments_overview(business_id: BusinessId, rt: RuntimeDep, status: PaymentStatus | None = None,
                      payee_id: str | None = None) -> PaymentsOverview:
    """Connection, payees, suggested payments from the business's records, and every request (newest first),
    optionally filtered by status or payee."""
    return rt.payments.overview(business_id, status=status, payee_id=payee_id)


@router.post("/businesses/{business_id}/payments/requests", response_model=PaymentView)
def create_payment(business_id: BusinessId, body: PaymentCreate, rt: RuntimeDep) -> PaymentView:
    """Create a pay request and put it to the gateway: it runs if a signed limit covers it, otherwise it returns
    `awaiting_approval` with the approval ID to sign."""
    return rt.payments.create(business_id, source=body.source, payee_id=body.payee_id,
                              amount_minor=body.amount_minor, reason=body.reason, reference=body.reference)


@router.get("/businesses/{business_id}/payments/requests/{request_id}", response_model=PaymentView)
def get_payment(business_id: BusinessId, request_id: RequestId, rt: RuntimeDep) -> PaymentView:
    return rt.payments.view(business_id, request_id)


@router.post("/businesses/{business_id}/payments/requests/{request_id}/cancel", response_model=PaymentView)
def cancel_payment(business_id: BusinessId, request_id: RequestId, rt: RuntimeDep) -> PaymentView:
    return rt.payments.cancel(business_id, request_id)


@router.post("/businesses/{business_id}/payments/requests/{request_id}/refresh", response_model=PaymentView)
def refresh_payment(business_id: BusinessId, request_id: RequestId, rt: RuntimeDep) -> PaymentView:
    """Ask the provider for the status of a sent payment, in case its webhook did not arrive."""
    return rt.payments.refresh(business_id, request_id)


@router.get("/businesses/{business_id}/payments/requests/{request_id}/receipt", response_model=Receipt)
def payment_receipt(business_id: BusinessId, request_id: RequestId, rt: RuntimeDep) -> Receipt:
    found = rt.payments.receipt(business_id, request_id)
    if found is None:
        raise PaymentsError("No receipt: the payment has not settled.")
    return Receipt(request_id=request_id, receipt_sha256=found[1], document=found[0])


@router.get("/businesses/{business_id}/payments/requests/{request_id}/onchain", response_model=LeafCheck)
def verify_payment_onchain(business_id: BusinessId, request_id: RequestId, rt: RuntimeDep) -> LeafCheck:
    """Recompute the receipt's hash from the stored receipt, find it in an anchored batch and check the root on
    chain (invariant 9: only the hash is published)."""
    found = rt.payments.receipt(business_id, request_id)
    if found is None:
        raise PaymentsError("No receipt: the payment has not settled.")
    document, recorded = found
    try:
        recomputed = canonical_hash(document)
    except CanonicalError:
        recomputed = "0" * 64
    return rt.anchors.verify_leaf("payment", recomputed, recorded)


@router.post("/businesses/{business_id}/payments/payees", response_model=Payee)
def add_payee(business_id: BusinessId, body: PayeeCreate, rt: RuntimeDep) -> Payee:
    """Add a payee. Needs the account number typed twice and an explicit confirmation."""
    return rt.payments.add_payee(business_id, body.name, body.account_number, body.confirm_account_number,
                                 body.confirmed)


@router.post("/businesses/{business_id}/payments/verifications", status_code=204)
def verify_call(business_id: BusinessId, body: CallVerification, rt: RuntimeDep) -> None:
    """Mark the call-script check done for a flagged email. Only then can it be paid (and still only with a
    signature)."""
    rt.payments.verify_call(business_id, body.email_id)


@router.get("/businesses/{business_id}/connections/payments", response_model=PaymentConnectionStatus)
def payment_connection(business_id: BusinessId, rt: RuntimeDep) -> PaymentConnectionStatus:
    return rt.payments.status(business_id)


@router.post("/businesses/{business_id}/connections/payments/connect", response_model=PaymentConnectStart)
def connect_payments(business_id: BusinessId, body: PaymentConnectRequest, rt: RuntimeDep) -> PaymentConnectStart:
    """Start the consent flow: the provider's consent URL (state + PKCE) to open in a popup."""
    return PaymentConnectStart(authorize_url=rt.payments.start(business_id, body.client_name))


@router.post("/businesses/{business_id}/connections/payments/disconnect", response_model=PaymentConnectionStatus)
def disconnect_payments(business_id: BusinessId, rt: RuntimeDep) -> PaymentConnectionStatus:
    """Revoke the token at the provider (immediately) and delete it here."""
    return rt.payments.disconnect(business_id)


def _page(rt, ok: bool, title: str, detail: str, business_id: str | None) -> HTMLResponse:
    origin = rt.settings.frontend_origin
    payload = json.dumps({"type": "payments-connection", "ok": ok, "business_id": business_id})
    script = (f"<script>try{{if(window.opener){{window.opener.postMessage({payload},{json.dumps(origin)});"
              f"setTimeout(function(){{window.close()}},1200)}}}}catch(e){{}}</script>")
    body = (f"<!doctype html><html><head><meta charset='utf-8'><title>{html.escape(title)}</title>"
            "<meta name='viewport' content='width=device-width,initial-scale=1'>"
            "<style>body{font-family:system-ui,sans-serif;max-width:32rem;margin:4rem auto;padding:0 1rem;"
            f"line-height:1.5}}</style></head><body><h1>{html.escape(title)}</h1><p>{html.escape(detail)}</p>"
            f"{script}</body></html>")
    return HTMLResponse(body, status_code=200 if ok else 400)


@router.get(CALLBACK_PATH, response_class=HTMLResponse, include_in_schema=False)
def payments_callback(rt: RuntimeDep, state: str | None = None, code: str | None = None,
                      error: str | None = None) -> HTMLResponse:
    try:
        business_id = rt.payments.finish(state, code, error)
    except PaymentsError as exc:
        return _page(rt, False, "Payment service not connected", str(exc), None)
    return _page(rt, True, "Payment service connected", "You can close this window.", business_id)


@router.post(WEBHOOK_PREFIX + "{business_id}", response_model=WebhookResult, include_in_schema=False)
async def payments_webhook(business_id: BusinessId, request: Request, rt: RuntimeDep,
                           x_sandboxpay_signature: str | None = Header(default=None)) -> JSONResponse:
    body = await request.body()
    with rt.business(business_id):
        pass
    accepted, outcome = rt.payments.webhook(business_id, body[:65536], x_sandboxpay_signature)
    return JSONResponse({"accepted": accepted, "outcome": outcome}, status_code=200 if accepted else 401)
