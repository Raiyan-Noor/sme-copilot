"""Payments test harness: the app and the SandboxPay provider as two in-process apps wired to each other through
test clients, so the whole flow (consent, token exchange, payment, signed webhook) runs with no network.

The app reaches the provider through a `Transport` over the provider's TestClient; the provider's webhooks reach the
app through a poster over the app's TestClient. Settlement is driven by hand (`settle()`), not by a timer.
"""

import json
import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from app.connections.http import Response
from app.services.payments import PaymentsService
from sandboxpay.main import create_app as create_provider_app
from sandboxpay.provider import ProviderConfig, SandboxPay
from tests.agent_env import agent_client
from tests.gateway_env import Owner
from tests.owner_api import approve, enroll, grant

MAYA = "maya-corner-store"
PROVIDER = "http://sandboxpay.test"
SECRET = "test-client-secret"
TOKEN_KEY = "ab" * 32
REDIRECT = "http://localhost:8000/payments/sandboxpay/callback"


class ClientTransport:
    """app.connections.http.Transport over a TestClient (the provider)."""

    def __init__(self, client: TestClient):
        self.client = client
        self.down = False

    def request(self, method: str, url: str, *, headers=None, form=None, json_body=None) -> Response:
        if self.down:
            from app.connections.http import TransportError

            raise TransportError("ConnectionRefusedError")
        parts = urllib.parse.urlsplit(url)
        path = parts.path + (f"?{parts.query}" if parts.query else "")
        r = self.client.request(method, path, headers=headers or {}, data=form, json=json_body)
        try:
            body: Any = r.json()
        except ValueError:
            body = r.text
        return Response(r.status_code, body)


@dataclass
class PayEnv:
    app: TestClient
    provider: SandboxPay
    provider_client: TestClient
    transport: ClientTransport
    business: str = MAYA
    owner: Owner | None = None
    webhooks: list[tuple[int, dict]] = field(default_factory=list)
    drop_webhooks: bool = False

    @property
    def rt(self):
        return self.app.app.state.runtime

    def url(self, path: str) -> str:
        return f"/businesses/{self.business}{path}"

    # Consent ----------------------------------------------------------------------------------------------------
    def connect(self, per_payment: float | None = None, daily: float | None = None, decision: str = "approve") -> dict:
        r = self.app.post(self.url("/connections/payments/connect"), json={"client_name": "Test app"})
        assert r.status_code == 200, r.text
        q = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(r.json()["authorize_url"]).query))
        page = self.provider_client.get("/authorize", params=q)
        assert page.status_code == 200, page.text
        form = {"client_id": q["client_id"], "redirect_uri": q["redirect_uri"], "state": q["state"],
                "code_challenge": q["code_challenge"], "scope": q["scope"],
                "requested_per_payment": q["per_payment_cap"], "requested_daily": q["daily_cap"],
                "currency": q["currency"], "account_name": q["account_name"],
                "per_payment": per_payment if per_payment is not None else int(q["per_payment_cap"]) / 100,
                "daily": daily if daily is not None else int(q["daily_cap"]) / 100, "decision": decision}
        back = self.provider_client.post("/authorize", data=form, follow_redirects=False)
        assert back.status_code == 303, back.text
        loc = urllib.parse.urlsplit(back.headers["location"])
        done = self.app.get(loc.path + "?" + loc.query)
        return {"status": done.status_code, "page": done.text, "query": q}

    # Owner actions ------------------------------------------------------------------------------------------------
    def enroll(self) -> Owner:
        self.owner = self.owner or enroll(self.app, self.business)
        return self.owner

    def grant_bills(self, cap: int, payees: list[str]) -> dict:
        return grant(self.app, self.business, self.enroll(), "pay_recurring_bill", cap, payees)

    def overview(self, **params) -> dict:
        r = self.app.get(self.url("/payments"), params=params)
        assert r.status_code == 200, r.text
        return r.json()

    def create(self, **body) -> dict:
        r = self.app.post(self.url("/payments/requests"), json=body)
        assert r.status_code == 200, r.text
        return r.json()

    def approve(self, request: dict, **extra) -> dict:
        return approve(self.app, self.business, request["approval_id"], self.enroll(), **extra)

    def get(self, request_id: str) -> dict:
        return self.app.get(self.url(f"/payments/requests/{request_id}")).json()

    def settle(self) -> list[str]:
        return self.provider.settle_due(force=True)

    def ledger_rows(self, request_id: str) -> list[dict]:
        with self.rt.business(self.business) as conn:
            return [dict(r) for r in conn.execute("SELECT * FROM transactions WHERE id = ?", (f"txn_{request_id}",))]

    def audit_kinds(self) -> list[str]:
        return [e.kind for e in self.rt.audit.entries()]


def payments_env(data_dir: Path, seed_dir: Path, *, fail_accounts: tuple[str, ...] = (), **overrides) -> PayEnv:
    """The app over copied tenants with a fresh SandboxPay beside it."""
    settings = {"sandboxpay_url": PROVIDER, "sandboxpay_client_secret": SECRET, "sandboxpay_token_key": TOKEN_KEY,
                "sandboxpay_redirect_uri": REDIRECT,
                "sandboxpay_webhook_base": "http://testserver/payments/sandboxpay/webhook", **overrides}
    app = agent_client(data_dir, seed_dir, **settings)
    env_box: dict[str, PayEnv] = {}

    def post(url: str, body: bytes, headers: dict[str, str]) -> int:
        env = env_box["env"]
        if env.drop_webhooks:
            return 503
        r = app.post(urllib.parse.urlsplit(url).path, content=body,
                     headers={**headers, "Content-Type": "application/json"})
        env.webhooks.append((r.status_code, json.loads(body)))
        return r.status_code

    provider = SandboxPay(data_dir.parent / f"{data_dir.name}-sandboxpay.sqlite", ProviderConfig(
        client_id="sme-copilot", client_secret=SECRET, redirect_uris=(REDIRECT,),
        webhook_prefixes=("http://testserver/payments/sandboxpay/webhook/",), settle_seconds=0,
        fail_accounts=frozenset(fail_accounts)), post=post)
    provider_client = TestClient(create_provider_app(provider, settle_worker=False))
    transport = ClientTransport(provider_client)
    rt = app.app.state.runtime
    rt._payments = PaymentsService(rt, transport)
    env = PayEnv(app, provider, provider_client, transport)
    env_box["env"] = env
    return env
