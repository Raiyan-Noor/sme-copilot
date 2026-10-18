"""The owner's side of the gateway over HTTP, for suites that drive the whole app: enrol a key, sign standing
mandates and approvals in the "browser" (the test holds the private key), and propose directly as an API caller."""

from typing import Any

from fastapi.testclient import TestClient

from tests.gateway_env import Owner


def gw(business: str) -> str:
    return f"/businesses/{business}/gateway"


def enroll(client: TestClient, business: str, owner: Owner | None = None) -> Owner:
    owner = owner or Owner()
    r = client.post(f"{gw(business)}/owner-key", json={"public_key": owner.public_key})
    assert r.status_code == 200, r.text
    return owner


def draft_mandate(client: TestClient, business: str, action: str, cap: int, allowlist: list[str],
                  days: int = 30) -> dict[str, Any]:
    r = client.post(f"{gw(business)}/mandates/draft", json={
        "action": action, "terms": {"max_amount_minor": cap, "allowlist": allowlist}, "days": days})
    assert r.status_code == 200, r.text
    return r.json()


def register(client: TestClient, business: str, owner: Owner, payload: dict, terms: dict,
             message: str) -> dict[str, Any]:
    """Sign `message` (the canonical payload bytes) with the owner's key and register the mandate."""
    signature = owner.key.sign(message.encode()).signature.hex()
    r = client.post(f"{gw(business)}/mandates", json={"payload": payload, "terms": terms, "signature": signature,
                                                       "public_key": owner.public_key})
    assert r.status_code == 200, r.text
    return r.json()


def grant(client: TestClient, business: str, owner: Owner, action: str, cap: int, allowlist: list[str],
          days: int = 30) -> dict[str, Any]:
    draft = draft_mandate(client, business, action, cap, allowlist, days)
    result = register(client, business, owner, draft["payload"], draft["terms"], draft["message"])
    assert result["accepted"], result
    return result


def sign_approval(client: TestClient, business: str, approval_id: str, owner: Owner) -> str:
    view = client.get(f"{gw(business)}/approvals/{approval_id}").json()
    return owner.key.sign(view["message"].encode()).signature.hex()


def approve(client: TestClient, business: str, approval_id: str, owner: Owner, signature: str | None = None,
            **extra) -> dict[str, Any]:
    signature = signature or sign_approval(client, business, approval_id, owner)
    r = client.post(f"{gw(business)}/approvals/{approval_id}/approve",
                    json={"signature": signature, "public_key": owner.public_key, **extra})
    assert r.status_code == 200, r.text
    return r.json()


def propose(client: TestClient, business: str, tool: str, untrusted: tuple[str, ...] = (), **args) -> dict:
    body = {"tool": tool, "args": {k: {"value": v, "provenance": "untrusted" if k in untrusted else "trusted"}
                                   for k, v in args.items()}}
    r = client.post(f"{gw(business)}/propose", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def runtime(client: TestClient):
    return client.app.state.runtime


def bank_ops(client: TestClient, business: str) -> list[dict]:
    return runtime(client).gateway(business).executors.bank.operations()


def outbox(client: TestClient, business: str) -> list[dict]:
    return runtime(client).gateway(business).executors.mailbox.outbox()
