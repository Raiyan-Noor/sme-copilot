"""Connected services: Gmail. Thin routes over services/gmail.py; every step is audited there.

The OAuth callback is the one public route here (Google redirects the owner's browser to it, without the passcode
header). It acts only on a one-time `state` issued by `connect`, and it never returns or renders a token.
"""

import html
import json
from typing import Literal

from fastapi import APIRouter, BackgroundTasks
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from app.api.deps import BusinessId, RuntimeDep
from app.services.gmail import ConnectError, GmailStatus

router = APIRouter(tags=["connections"])

CALLBACK_PATH = "/inbox/gmail/callback"


class GmailConnectStart(BaseModel):
    authorize_url: str


class InboxSourceChoice(BaseModel):
    source: Literal["gmail", "sandbox"]


class GmailPollResult(BaseModel):
    processed: list[str]


class GmailImportStarted(BaseModel):
    started: bool
    days: int


@router.get("/businesses/{business_id}/connections/gmail", response_model=GmailStatus)
def gmail_status(business_id: BusinessId, rt: RuntimeDep) -> GmailStatus:
    """Connection state, the connected address, and in plain language what the app can and cannot do with it."""
    return rt.gmail.status(business_id)


@router.post("/businesses/{business_id}/connections/gmail/connect", response_model=GmailConnectStart)
def gmail_connect(business_id: BusinessId, rt: RuntimeDep) -> GmailConnectStart:
    """Start the OAuth flow: the Google consent URL (state + PKCE) to open in a popup."""
    return GmailConnectStart(authorize_url=rt.gmail.start(business_id))


@router.post("/businesses/{business_id}/connections/gmail/disconnect", response_model=GmailStatus)
def gmail_disconnect(business_id: BusinessId, rt: RuntimeDep) -> GmailStatus:
    """Revoke the grant with Google and delete it here."""
    return rt.gmail.disconnect(business_id)


@router.put("/businesses/{business_id}/connections/gmail/source", response_model=GmailStatus)
def gmail_source(business_id: BusinessId, body: InboxSourceChoice, rt: RuntimeDep) -> GmailStatus:
    """Switch between reading (and sending) through Gmail and the sandbox inbox."""
    return rt.gmail.set_source(business_id, body.source)


@router.post("/businesses/{business_id}/connections/gmail/poll", response_model=GmailPollResult)
def gmail_poll(business_id: BusinessId, rt: RuntimeDep) -> GmailPollResult:
    """Check Gmail now instead of waiting for the background poll."""
    return GmailPollResult(processed=rt.gmail.poll(business_id, wait=True))


@router.post("/businesses/{business_id}/connections/gmail/import", response_model=GmailImportStarted)
def gmail_import_recent(business_id: BusinessId, rt: RuntimeDep, tasks: BackgroundTasks) -> GmailImportStarted:
    """Import the last 7 days of inbox mail through the same pipeline. Runs after the response; progress arrives
    on the inbox event stream."""
    if rt.gmail.store(business_id).get() is None:
        raise ConnectError("Connect Gmail first.")

    def run() -> None:
        try:
            rt.gmail.import_recent(business_id)
        except ConnectError:
            pass  # already audited

    tasks.add_task(run)
    return GmailImportStarted(started=True, days=7)


def _page(rt, ok: bool, title: str, detail: str, business_id: str | None) -> HTMLResponse:
    origin = rt.settings.frontend_origin
    payload = json.dumps({"type": "gmail-connection", "ok": ok, "business_id": business_id})
    script = (f"<script>try{{if(window.opener){{window.opener.postMessage({payload},{json.dumps(origin)});"
              f"setTimeout(function(){{window.close()}},1200)}}}}catch(e){{}}</script>")
    back = f'<p><a href="{html.escape(origin)}">Back to the app</a></p>' if origin else ""
    body = (f"<!doctype html><html><head><meta charset='utf-8'><title>{html.escape(title)}</title>"
            "<meta name='viewport' content='width=device-width,initial-scale=1'>"
            "<style>body{font-family:system-ui,sans-serif;max-width:32rem;margin:4rem auto;padding:0 1rem;"
            "line-height:1.5}</style></head>"
            f"<body><h1>{html.escape(title)}</h1><p>{html.escape(detail)}</p>{back}{script}</body></html>")
    return HTMLResponse(body, status_code=200 if ok else 400)


@router.get(CALLBACK_PATH, response_class=HTMLResponse, include_in_schema=False)
def gmail_callback(rt: RuntimeDep, state: str | None = None, code: str | None = None,
                   error: str | None = None) -> HTMLResponse:
    try:
        business_id, address = rt.gmail.finish(state, code, error)
    except ConnectError as exc:
        return _page(rt, False, "Gmail was not connected", str(exc), None)
    return _page(rt, True, "Gmail connected", f"Connected as {address}. You can close this window.", business_id)
