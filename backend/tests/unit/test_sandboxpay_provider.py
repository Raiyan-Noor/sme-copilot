"""SandboxPay on its own: consent can lower the caps but never raise them, codes are single-use and PKCE-bound,
webhooks go only to an allow-listed URL and carry a verifiable HMAC signature."""

import hashlib
import hmac
import json

import pytest

from sandboxpay.provider import ProviderConfig, ProviderError, SandboxPay, _challenge

REDIRECT = "http://localhost:8000/payments/sandboxpay/callback"
HOOK = "http://127.0.0.1:8000/payments/sandboxpay/webhook/"


@pytest.fixture
def sent():
    return []


@pytest.fixture
def provider(sent):
    def post(url, body, headers):
        sent.append((url, body, headers))
        return 200

    return SandboxPay(":memory:", ProviderConfig("client", "secret", (REDIRECT,), (HOOK,), settle_seconds=0), post=post)


def _code(p, verifier="v" * 50, per=1000, daily=2000):
    return p.approve(client_id="client", redirect_uri=REDIRECT, scope="payments.send payments.read",
                     challenge=_challenge(verifier), requested_per_payment=1000, requested_daily=2000,
                     per_payment_cap=per, daily_cap=daily, currency="usd", account_name="Shop")


def _token(p, **kw):
    return p.exchange(client_id="client", client_secret="secret", code=_code(p), code_verifier="v" * 50,
                      redirect_uri=REDIRECT, webhook_url=HOOK + "biz", **kw)


def test_consent_can_lower_but_not_raise_the_caps(provider):
    assert _code(provider, per=500, daily=900)
    with pytest.raises(ProviderError, match="invalid_limits"):
        _code(provider, per=1001)


def test_code_is_single_use_and_bound_to_the_pkce_verifier(provider):
    code = _code(provider)
    with pytest.raises(ProviderError, match="invalid_grant"):
        provider.exchange(client_id="client", client_secret="secret", code=code, code_verifier="w" * 50,
                          redirect_uri=REDIRECT, webhook_url=HOOK + "biz")
    grant = provider.exchange(client_id="client", client_secret="secret", code=code, code_verifier="v" * 50,
                              redirect_uri=REDIRECT, webhook_url=HOOK + "biz")
    assert grant["scope"] == "payments.send payments.read" and grant["currency"] == "USD"
    with pytest.raises(ProviderError, match="invalid_grant"):
        provider.exchange(client_id="client", client_secret="secret", code=code, code_verifier="v" * 50,
                          redirect_uri=REDIRECT, webhook_url=HOOK + "biz")


def test_wrong_client_secret_and_foreign_webhook_url_are_refused(provider):
    with pytest.raises(ProviderError, match="invalid_client"):
        provider.exchange(client_id="client", client_secret="nope", code=_code(provider), code_verifier="v" * 50,
                          redirect_uri=REDIRECT, webhook_url=HOOK + "biz")
    with pytest.raises(ProviderError, match="webhook_url_not_allowed"):
        provider.exchange(client_id="client", client_secret="secret", code=_code(provider), code_verifier="v" * 50,
                          redirect_uri=REDIRECT, webhook_url="http://evil.example/hook")


def test_settlement_webhook_is_signed_with_the_connection_secret(provider, sent):
    grant = _token(provider)
    status, payment = provider.create_payment(grant["access_token"], "key-00000001", {
        "payee_ref": "p", "account_token": "acct", "amount_minor": 700, "currency": "USD", "reference": "r"})
    assert status == 202 and payment["status"] == "processing"
    assert provider.settle_due() == [payment["id"]]
    url, body, headers = sent[-1]
    assert url == HOOK + "biz" and json.loads(body)["type"] == "payment.settled"
    expected = "sha256=" + hmac.new(grant["webhook_secret"].encode(), body, hashlib.sha256).hexdigest()
    assert headers["X-SandboxPay-Signature"] == expected
    assert provider.get_payment(grant["access_token"], payment["id"])["status"] == "settled"


def test_revoked_token_stops_working_at_once(provider):
    grant = _token(provider)
    assert provider.revoke(grant["access_token"])
    with pytest.raises(ProviderError, match="token_revoked"):
        provider.create_payment(grant["access_token"], "key-00000002", {})
