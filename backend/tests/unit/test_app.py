"""Health route, passcode auth (fail closed, constant-time) and CORS."""

from fastapi.testclient import TestClient

from app.main import PASSCODE_HEADER, create_app
from tests.helpers import TEST_ORIGIN, TEST_PASSCODE, make_settings

PROTECTED = "/no-such-route"  # any non-public path goes through auth before routing


def test_health_is_public(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_missing_passcode_is_rejected(client):
    assert client.get(PROTECTED).status_code == 401


def test_wrong_passcode_is_rejected(client):
    assert client.get(PROTECTED, headers={PASSCODE_HEADER: "wrong"}).status_code == 401


def test_correct_passcode_passes_auth(client):
    # Passes auth, then 404s because the route doesn't exist.
    assert client.get(PROTECTED, headers={PASSCODE_HEADER: TEST_PASSCODE}).status_code == 404


def test_unset_passcode_fails_closed():
    client = TestClient(create_app(make_settings(demo_passcode="")))
    assert client.get(PROTECTED).status_code == 503
    assert client.get(PROTECTED, headers={PASSCODE_HEADER: ""}).status_code == 503
    assert client.get("/health").status_code == 200


def test_cors_preflight_allowed_origin(client):
    r = client.options(
        "/health",
        headers={"Origin": TEST_ORIGIN, "Access-Control-Request-Method": "GET"},
    )
    assert r.status_code == 200
    assert r.headers["access-control-allow-origin"] == TEST_ORIGIN


def test_cors_rejects_unknown_origin(client):
    r = client.get("/health", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in r.headers


def test_401_carries_cors_headers(client):
    r = client.get(PROTECTED, headers={"Origin": TEST_ORIGIN})
    assert r.status_code == 401
    assert r.headers["access-control-allow-origin"] == TEST_ORIGIN


def test_openapi_declares_passcode_scheme(client):
    schema = client.get("/openapi.json").json()
    assert schema["components"]["securitySchemes"]["Passcode"]["name"] == PASSCODE_HEADER
