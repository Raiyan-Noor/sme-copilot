"""SandboxPay's HTTP API (run separately: `uvicorn --factory sandboxpay.main:create_app --port 8100`,
started by `make dev`).

  GET  /authorize            consent screen: what the client may do, with the caps the owner can lower
  POST /authorize            the owner's decision; redirects back to the client with a one-time code
  POST /oauth/token          code + PKCE verifier + client secret -> scoped bearer token and webhook secret
  POST /oauth/revoke         revoke a token immediately
  GET  /v1/connection        scopes, caps and today's spend for the calling token
  POST /v1/payments          create a payment (Idempotency-Key header required) -> 202 processing
  GET  /v1/payments/{id}     one payment's status

Settings come from the environment (and the repo-root .env): SANDBOXPAY_CLIENT_ID, SANDBOXPAY_CLIENT_SECRET,
SANDBOXPAY_REDIRECT_URIS, SANDBOXPAY_WEBHOOK_PREFIXES, SANDBOXPAY_SETTLE_SECONDS, SANDBOXPAY_FAIL_ACCOUNTS,
SANDBOXPAY_DATA_DIR. Synthetic only: no real money, no real accounts.
"""

import html
import threading
import urllib.parse
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Form, Header, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from sandboxpay.provider import ProviderConfig, ProviderError, SandboxPay

REPO_ROOT = Path(__file__).resolve().parents[2]


class ProviderSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SANDBOXPAY_", env_file=REPO_ROOT / ".env",
                                      env_file_encoding="utf-8", extra="ignore")

    client_id: str = "sme-copilot"
    client_secret: str = ""
    redirect_uris: str = ("http://localhost:8000/payments/sandboxpay/callback,"
                          "http://127.0.0.1:8000/payments/sandboxpay/callback")
    webhook_prefixes: str = "http://127.0.0.1:8000/payments/sandboxpay/webhook/,http://localhost:8000/payments/sandboxpay/webhook/"
    settle_seconds: float = Field(default=4.0, ge=0)
    fail_accounts: str = ""
    data_dir: Path = REPO_ROOT / "backend" / "data" / "sandboxpay"

    def config(self) -> ProviderConfig:
        split = lambda s: tuple(x.strip() for x in s.split(",") if x.strip())  # noqa: E731
        return ProviderConfig(client_id=self.client_id, client_secret=self.client_secret,
                              redirect_uris=split(self.redirect_uris), webhook_prefixes=split(self.webhook_prefixes),
                              settle_seconds=self.settle_seconds, fail_accounts=frozenset(split(self.fail_accounts)))


def _money(minor: int, currency: str) -> str:
    return f"{currency} {minor / 100:,.2f}"


def _page(title: str, body: str, status: int = 200) -> HTMLResponse:
    return HTMLResponse(
        "<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,"
        f"initial-scale=1'><title>{html.escape(title)}</title><style>body{{font-family:system-ui,sans-serif;"
        "max-width:30rem;margin:3rem auto;padding:0 1rem;line-height:1.5}label{display:block;margin:.6rem 0}"
        "input{font:inherit;padding:.3rem;width:9rem}button{font:inherit;padding:.5rem 1rem;margin-right:.5rem}"
        ".tag{font-size:.8rem;text-transform:uppercase;letter-spacing:.06em;opacity:.7}</style></head><body>"
        f"<div class='tag'>SandboxPay · simulated provider · no real money</div>{body}</body></html>", status)


def create_app(provider: SandboxPay | None = None, *, settle_worker: bool = True) -> FastAPI:
    if provider is None:  # tests pass their own provider and never read .env
        settings = ProviderSettings()
        provider = SandboxPay(settings.data_dir / "sandboxpay.sqlite", settings.config())

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        stop = threading.Event()
        worker = threading.Thread(target=provider.run_forever, args=(stop,), daemon=True) if settle_worker else None
        if worker:
            worker.start()
        yield
        stop.set()

    app = FastAPI(title="SandboxPay (simulated provider)", version="0.1.0", lifespan=lifespan)
    app.state.provider = provider

    @app.exception_handler(ProviderError)
    async def refused(_: Request, exc: ProviderError) -> JSONResponse:
        return JSONResponse({"error": exc.code, "detail": exc.detail}, status_code=exc.status)

    def bearer(authorization: str | None) -> str | None:
        return authorization.removeprefix("Bearer ").strip() if authorization else None

    @app.get("/", response_class=HTMLResponse)
    def home() -> HTMLResponse:
        return _page("SandboxPay", "<h1>SandboxPay</h1><p>A simulated payment provider for local demos.</p>")

    @app.get("/authorize", response_class=HTMLResponse)
    def authorize(client_id: str, redirect_uri: str, state: str, code_challenge: str, scope: str,
                  per_payment_cap: int, daily_cap: int, currency: str, client_name: str = "An app",
                  account_name: str = "Your business", code_challenge_method: str = "S256") -> HTMLResponse:
        try:
            if code_challenge_method != "S256":
                raise ProviderError(400, "pkce_s256_required")
            scopes = provider.check_authorize(client_id, redirect_uri, scope, per_payment_cap, daily_cap)
        except ProviderError as exc:
            return _page("Cannot connect", f"<h1>Cannot connect</h1><p>{html.escape(exc.detail)}</p>", exc.status)
        cur = html.escape(currency.upper()[:3])
        name, acct = html.escape(client_name[:60]), html.escape(account_name[:80])
        can = {"payments.send": "Send payments from this account to payees you have approved, within the limits below",
               "payments.read": "See the status of the payments it sent"}
        items = "".join(f"<li>{html.escape(can[s])}</li>" for s in scopes)
        hidden = "".join(f"<input type='hidden' name='{k}' value='{html.escape(str(v))}'>" for k, v in {
            "client_id": client_id, "redirect_uri": redirect_uri, "state": state, "code_challenge": code_challenge,
            "scope": " ".join(scopes), "requested_per_payment": per_payment_cap, "requested_daily": daily_cap,
            "currency": currency, "account_name": account_name}.items())
        body = (f"<h1>Connect {name} to SandboxPay</h1><p>Account: <b>{acct}</b></p>"
                f"<p>{name} is asking to:</p><ul>{items}</ul>"
                "<p>SandboxPay enforces these limits itself, whatever the app asks for later. You can lower them now; "
                "you cannot raise them later without connecting again.</p>"
                f"<form method='post' action='/authorize'>{hidden}"
                f"<label>Most per payment ({cur}) <input name='per_payment' type='number' step='0.01' min='0.01' "
                f"max='{per_payment_cap / 100:.2f}' value='{per_payment_cap / 100:.2f}'></label>"
                f"<label>Most per day ({cur}) <input name='daily' type='number' step='0.01' min='0.01' "
                f"max='{daily_cap / 100:.2f}' value='{daily_cap / 100:.2f}'></label>"
                f"<p>It cannot: change your payees' bank details, raise these limits, or move money anywhere else.</p>"
                "<button name='decision' value='approve'>Approve</button>"
                "<button name='decision' value='deny'>Deny</button></form>")
        return _page("Connect to SandboxPay", body)

    @app.post("/authorize")
    def authorize_decision(client_id: str = Form(), redirect_uri: str = Form(), state: str = Form(),
                           code_challenge: str = Form(), scope: str = Form(), requested_per_payment: int = Form(),
                           requested_daily: int = Form(), currency: str = Form(), account_name: str = Form(),
                           per_payment: float = Form(), daily: float = Form(), decision: str = Form()):
        if redirect_uri not in provider.config.redirect_uris:
            return _page("Cannot connect", "<h1>Cannot connect</h1><p>Unknown redirect address.</p>", 400)
        sep = "&" if "?" in redirect_uri else "?"
        if decision != "approve":
            return RedirectResponse(redirect_uri + sep + urllib.parse.urlencode(
                {"error": "access_denied", "state": state}), status_code=303)
        try:
            code = provider.approve(client_id=client_id, redirect_uri=redirect_uri, scope=scope,
                                    challenge=code_challenge, requested_per_payment=requested_per_payment,
                                    requested_daily=requested_daily, per_payment_cap=round(per_payment * 100),
                                    daily_cap=round(daily * 100), currency=currency, account_name=account_name)
        except ProviderError as exc:
            return _page("Cannot connect", f"<h1>Cannot connect</h1><p>{html.escape(exc.detail)}</p>", exc.status)
        return RedirectResponse(redirect_uri + sep + urllib.parse.urlencode({"code": code, "state": state}),
                                status_code=303)

    @app.post("/oauth/token")
    async def token(request: Request) -> dict:
        b = await request.json()
        return provider.exchange(client_id=str(b.get("client_id", "")), client_secret=str(b.get("client_secret", "")),
                                 code=str(b.get("code", "")), code_verifier=str(b.get("code_verifier", "")),
                                 redirect_uri=str(b.get("redirect_uri", "")), webhook_url=str(b.get("webhook_url", "")))

    @app.post("/oauth/revoke")
    async def revoke(request: Request) -> dict:
        b = await request.json()
        return {"revoked": provider.revoke(str(b.get("token", "")))}

    @app.get("/v1/connection")
    def connection(authorization: str | None = Header(default=None)) -> dict:
        return provider.connection_view(bearer(authorization))

    @app.post("/v1/payments")
    async def create_payment(request: Request, authorization: str | None = Header(default=None),
                             idempotency_key: str | None = Header(default=None)) -> JSONResponse:
        token_value = bearer(authorization)
        provider.connection(token_value)  # 401 before reading the body
        status, body = provider.create_payment(token_value, idempotency_key, await request.json())
        return JSONResponse(body, status_code=status)

    @app.get("/v1/payments/{payment_id}")
    def get_payment(payment_id: str, authorization: str | None = Header(default=None)) -> dict:
        return provider.get_payment(bearer(authorization), payment_id)

    return app
