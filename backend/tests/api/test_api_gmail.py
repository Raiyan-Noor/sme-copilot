"""Gmail over OAuth (P6), against a fake Google: no network in CI.

Covers the connect/callback flow (state, PKCE, scopes), token encryption at rest, new mail through the same
quarantine -> sentinel pipeline as the sandbox mailbox (with the extractor replayed from the mailbox recordings,
since the extractor's input does not depend on where a message came from), a malicious attachment held, sending
limited to DEMO_SEND_ALLOWLIST, disconnect revoking and deleting the token, reconnect-needed handling, and the planner
never seeing the token or the raw email.
"""

import base64
import hashlib
import json
import urllib.parse
from pathlib import Path

import pytest

from app.connections.crypto import TokenCipher, TokenKeyMissing
from app.connections.gmail import API_URL, REVOKE_URL, SCOPES, TOKEN_URL
from app.connections.http import Response, TransportError
from app.services.gmail import GmailService
from tests.agent_env import MAYA, FakeLLM, agent_client, build_template, calls, copy_data_dir, llm_settings, text
from tests.owner_api import enroll, grant, outbox

TOKEN_KEY = "ab" * 32
REFRESH = "1//refresh-token-SECRET"
ACCESS = "ya29.access-token-SECRET"
ACCOUNT = "demo.shop@gmail.example"
CUSTOMER = "cus_sunrise"
CUSTOMER_EMAIL = "orders@sunrisecafe.example"


class FakeGoogle:
    """Google's OAuth and Gmail endpoints, in memory. Records every request."""

    def __init__(self, mail: dict[str, bytes]):
        self.mail = mail
        self.requests: list[tuple[str, str, dict | None, dict | None]] = []
        self.history_id = 1000
        self.new: list[str] = []  # message IDs the next history call reports
        self.revoked: list[str] = []
        self.sent: list[bytes] = []
        self.refresh_error: str | None = None
        self.down = False

    def request(self, method, url, *, headers=None, form=None, json_body=None):
        self.requests.append((method, url, form, json_body))
        if self.down:
            raise TransportError("ConnectionRefusedError")
        if url == TOKEN_URL:
            if form["grant_type"] == "authorization_code":
                self.verifier = form["code_verifier"]
                return Response(200, {"access_token": ACCESS, "expires_in": 3599, "refresh_token": REFRESH,
                                      "scope": " ".join(SCOPES), "token_type": "Bearer"})
            if self.refresh_error:
                return Response(400, {"error": self.refresh_error})
            assert form["refresh_token"] == REFRESH
            return Response(200, {"access_token": ACCESS, "expires_in": 3599, "scope": " ".join(SCOPES)})
        if url == REVOKE_URL:
            self.revoked.append(form["token"])
            return Response(200, {})
        assert headers and headers["Authorization"] == f"Bearer {ACCESS}"
        path, _, query = url.removeprefix(API_URL + "/").partition("?")
        params = dict(urllib.parse.parse_qsl(query))
        if path == "profile":
            return Response(200, {"emailAddress": ACCOUNT, "historyId": str(self.history_id)})
        if path == "history":
            new, self.new = self.new, []
            self.history_id += len(new)
            return Response(200, {"historyId": str(self.history_id),
                                  "history": [{"messagesAdded": [{"message": {"id": m}}]} for m in new]})
        if path == "messages/send":
            self.sent.append(base64.urlsafe_b64decode(json_body["raw"]))
            return Response(200, {"id": "18f0sent0000001"})
        if path == "messages":
            return Response(200, {"messages": [{"id": m} for m in reversed(list(self.mail))]})
        if path.startswith("messages/") and params.get("format") == "raw":
            raw = self.mail[path.removeprefix("messages/")]
            return Response(200, {"raw": base64.urlsafe_b64encode(raw).decode(), "labelIds": ["INBOX", "UNREAD"]})
        return Response(404, {"error": {"code": 404}})


@pytest.fixture(scope="module")
def template(tmp_path_factory):
    """Seeded tenants with an empty inbox (fixed PII key, so extractor recordings replay)."""
    return build_template(tmp_path_factory.mktemp("gmail"))


@pytest.fixture
def env(template, tmp_path):
    data_dir, seed_dir = template
    dest = copy_data_dir(data_dir, tmp_path / "tenants")
    mailbox = seed_dir / "mailbox"
    google = FakeGoogle({"18f0aaaa00000003": (mailbox / "em-003.eml").read_bytes(),
                         "18f0aaaa00000016": (mailbox / "em-016.eml").read_bytes()})

    def make(**overrides):
        settings = {"gmail_client_id": "client-id.apps.example", "gmail_client_secret": "client-SECRET",
                    "gmail_token_key": TOKEN_KEY, **llm_settings(False), **overrides}
        client = agent_client(dest, seed_dir, **settings)
        rt = client.app.state.runtime
        rt._gmail = GmailService(rt, transport=google)
        return client

    return make, google, dest


def gm(business: str = MAYA) -> str:
    return f"/businesses/{business}/connections/gmail"


def connect(client) -> dict:
    url = client.post(f"{gm()}/connect").json()["authorize_url"]
    q = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(url).query))
    r = client.get("/inbox/gmail/callback", params={"state": q["state"], "code": "4/auth-code"})
    assert r.status_code == 200, r.text
    return q


def audit_text(data_dir) -> str:
    return (data_dir / "audit.jsonl").read_text(encoding="utf-8")


# ---- Configuration and connect ---------------------------------------------------------------------------------

def test_not_configured_says_which_settings_are_missing(env):
    make, _, _ = env
    client = make(gmail_client_id="", gmail_token_key="")
    status = client.get(gm()).json()
    assert status["state"] == "not_configured" and status["configured"] is False
    assert status["missing_settings"] == ["GMAIL_CLIENT_ID", "GMAIL_TOKEN_KEY"]
    assert status["can_do"] and status["cannot_do"]  # plain-language consent text, shown before redirecting
    assert client.post(f"{gm()}/connect").status_code == 422


def test_connect_uses_pkce_state_and_only_two_scopes(env):
    make, google, data_dir = env
    client = make()
    q = connect(client)
    assert q["scope"].split() == list(SCOPES)
    assert q["code_challenge_method"] == "S256" and q["access_type"] == "offline"
    challenge = base64.urlsafe_b64encode(hashlib.sha256(google.verifier.encode()).digest()).rstrip(b"=").decode()
    assert q["code_challenge"] == challenge  # the verifier stayed on the server until the exchange
    status = client.get(gm()).json()
    assert status["state"] == "connected" and status["email_address"] == ACCOUNT and status["source"] == "gmail"
    assert REFRESH not in json.dumps(status) and ACCESS not in json.dumps(status)
    log = audit_text(data_dir)
    assert "gmail.connected" in log and REFRESH not in log and ACCESS not in log and "client-SECRET" not in log


def test_callback_rejects_unknown_reused_and_cancelled_state(env):
    make, _, data_dir = env
    client = make()
    assert client.get("/inbox/gmail/callback", params={"state": "forged", "code": "x"}).status_code == 400
    q = connect(client)
    replay = client.get("/inbox/gmail/callback", params={"state": q["state"], "code": "4/auth-code"})
    assert replay.status_code == 400  # one-time state
    url = client.post(f"{gm()}/connect").json()["authorize_url"]
    state = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(url).query))["state"]
    denied = client.get("/inbox/gmail/callback", params={"state": state, "error": "access_denied"})
    assert denied.status_code == 400 and "cancelled" in denied.text
    assert audit_text(data_dir).count("gmail.connect_failed") == 3


def test_callback_is_public_but_other_gmail_routes_need_the_passcode(env):
    make, _, _ = env
    client = make()
    client.headers.pop("X-Passcode")
    assert client.get(gm()).status_code == 401
    assert client.post(f"{gm()}/connect").status_code == 401
    assert client.get("/inbox/gmail/callback", params={"state": "x", "code": "y"}).status_code == 400


def test_refresh_token_is_encrypted_at_rest(env):
    make, _, data_dir = env
    connect(make())
    stored = (data_dir / MAYA / "gmail.sqlite").read_bytes()
    assert REFRESH.encode() not in stored
    conn = GmailService(make().app.state.runtime).store(MAYA).get()
    assert TokenCipher(TOKEN_KEY).decrypt(conn.refresh_token_enc) == REFRESH
    with pytest.raises(TokenKeyMissing):
        TokenCipher("cd" * 32).decrypt(conn.refresh_token_enc)


# ---- Reading mail ----------------------------------------------------------------------------------------------

def test_only_mail_after_connecting_is_read_and_goes_through_the_pipeline(env):
    make, google, data_dir = env
    client = make()
    connect(client)
    assert client.post(f"{gm()}/poll").json()["processed"] == []  # nothing old is imported
    google.new = ["18f0aaaa00000003"]
    assert client.post(f"{gm()}/poll").json()["processed"] == ["gm-18f0aaaa00000003"]
    items = client.get(f"/businesses/{MAYA}/inbox").json()["items"]
    [item] = items
    assert item["record"]["source"] == "gmail" and item["record"]["sentinel"]["hold"] is False
    assert set(item["record"]["fields"]["extraction_status"].values()) == {"ok"}
    detail = client.get(f"/businesses/{MAYA}/inbox/gm-18f0aaaa00000003")
    assert detail.status_code == 200 and detail.json()["body_text"]
    entries = [json.loads(line) for line in audit_text(data_dir).splitlines()]
    received = [e for e in entries if e["kind"] == "quarantine.received"]
    assert received[-1]["data"]["source"] == "gmail"
    llm = [e for e in entries if e["kind"] == "llm.call"]
    assert llm and all(e["data"]["role"] == "extractor" and e["data"]["cache"] == "hit" for e in llm)
    stages = [e.stage for e in client.app.state.runtime.inbox_events.since(MAYA, 0) if e.kind == "message"]
    assert stages == ["received", "extracting", "checking", "accepted"]
    google.new = ["18f0aaaa00000003"]
    assert client.post(f"{gm()}/poll").json()["processed"] == []  # never twice


def test_malicious_attachment_from_gmail_is_held(env, attack):
    attack("ATK-PDF-HIDDEN-INSTRUCTIONS", "planted PDF arriving through real Gmail (mocked)", "live_llm")
    make, google, _ = env
    client = make()
    connect(client)
    google.new = ["18f0aaaa00000016"]
    client.post(f"{gm()}/poll")
    report = client.get(f"/businesses/{MAYA}/inbox").json()["items"][0]["record"]["sentinel"]
    codes = {f["code"] for f in report["flags"]}
    assert report["hold"] and {"instruction_like_text", "hidden_text"} <= codes, codes
    stages = [e.stage for e in client.app.state.runtime.inbox_events.since(MAYA, 0) if e.kind == "message"]
    assert stages[-1] == "held"
    for code in sorted(codes):
        attack.caught("quarantine" if code == "instruction_like_text" else "sentinel", code)


def test_import_last_seven_days_skips_mail_already_seen(env):
    make, google, _ = env
    client = make()
    connect(client)
    google.new = ["18f0aaaa00000003"]
    client.post(f"{gm()}/poll")
    assert client.post(f"{gm()}/import").json() == {"started": True, "days": 7}
    ids = sorted(i["record"]["email_id"] for i in client.get(f"/businesses/{MAYA}/inbox").json()["items"])
    assert ids == ["gm-18f0aaaa00000003", "gm-18f0aaaa00000016"]


def test_revoked_grant_needs_reconnect_and_sandbox_keeps_working(env):
    make, google, data_dir = env
    client = make()
    connect(client)
    client.app.state.runtime.gmail._tokens.clear()
    google.refresh_error = "invalid_grant"
    client.post(f"{gm()}/poll")
    status = client.get(gm()).json()
    assert status["state"] == "reconnect_needed" and "reconnect" in status["message"]
    assert client.post(f"/businesses/{MAYA}/inbox/sync").status_code == 200  # sandbox mailbox unaffected
    assert "gmail.reconnect_needed" in audit_text(data_dir)


def test_network_failure_backs_off_then_recovers(env):
    make, google, data_dir = env
    client = make()
    connect(client)
    google.down = True
    client.post(f"{gm()}/poll")
    assert client.get(gm()).json()["state"] == "unreachable"
    n = len(google.requests)
    client.app.state.runtime.gmail.poll(MAYA)  # within the backoff window: no request at all
    assert len(google.requests) == n
    google.down = False
    client.post(f"{gm()}/poll")  # a manual check waits out nothing
    assert client.get(gm()).json()["state"] == "connected"
    assert "gmail.poll_failed" in audit_text(data_dir) and "gmail.recovered" in audit_text(data_dir)


def test_switch_between_gmail_and_sandbox(env):
    make, google, _ = env
    client = make()
    assert client.put(f"{gm()}/source", json={"source": "gmail"}).status_code == 422  # not connected
    connect(client)
    assert client.put(f"{gm()}/source", json={"source": "sandbox"}).json()["source"] == "sandbox"
    google.new = ["18f0aaaa00000003"]
    assert client.post(f"{gm()}/poll").json()["processed"] == []  # paused
    assert client.put(f"{gm()}/source", json={"source": "gmail"}).json()["source"] == "gmail"
    assert client.post(f"{gm()}/poll").json()["processed"] == ["gm-18f0aaaa00000003"]


# ---- Sending ---------------------------------------------------------------------------------------------------

def _reminder(client):
    owner = enroll(client, MAYA)
    grant(client, MAYA, owner, "send_invoice_reminder", 40_000, [CUSTOMER])
    r = client.post(f"/businesses/{MAYA}/gateway/propose", json={
        "tool": "send_invoice_reminder",
        "args": {"customer_id": {"value": CUSTOMER, "provenance": "trusted"},
                 "invoice_id": {"value": "INV-1", "provenance": "trusted"},
                 "invoice_amount_minor": {"value": 12_000, "provenance": "trusted"}}})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "executed", r.json()
    return r.json()["result"]


def test_send_goes_through_gmail_only_to_allowlisted_recipients(env):
    make, google, _ = env
    client = make()  # empty allowlist
    connect(client)
    result = _reminder(client)
    assert result["transport"] == "sandbox" and "DEMO_SEND_ALLOWLIST" in result["label"]
    assert google.sent == [] and outbox(client, MAYA)[-1]["transport"] == "sandbox"


def test_send_to_allowlisted_recipient_uses_gmail(env):
    make, google, data_dir = env
    client = make(demo_send_allowlist=f" {CUSTOMER_EMAIL.upper()} ,other@example.com")
    connect(client)
    result = _reminder(client)
    assert result["transport"] == "gmail" and result["to_domain"] == "sunrisecafe.example"
    [sent] = google.sent
    assert CUSTOMER_EMAIL.encode() in sent and ACCOUNT.encode() in sent and b"INV-1" in sent
    assert outbox(client, MAYA)[-1]["gmail_message_id"] == "18f0sent0000001"
    assert CUSTOMER_EMAIL not in audit_text(data_dir)  # the audit log keeps the domain, not the address


def test_only_the_gateway_executor_calls_gmail_send():
    """Invariant 1 for real email: Gmail's send endpoint appears in exactly one module, under app/executor."""
    app_dir = Path(__file__).resolve().parents[2] / "app"
    users = sorted(p.relative_to(app_dir).as_posix() for p in app_dir.rglob("*.py")
                   if "messages/send" in p.read_text(encoding="utf-8"))
    assert users == ["executor/gmail_sender.py"]


def test_without_gmail_reminders_stay_in_the_sandbox_outbox(env):
    make, google, _ = env
    client = make(demo_send_allowlist=CUSTOMER_EMAIL)
    result = _reminder(client)
    assert result["transport"] == "sandbox" and google.sent == []


# ---- Disconnect ------------------------------------------------------------------------------------------------

def test_disconnect_revokes_with_google_and_deletes_the_token(env):
    make, google, data_dir = env
    client = make()
    connect(client)
    status = client.post(f"{gm()}/disconnect").json()
    assert status["state"] == "disconnected" and status["email_address"] is None and status["source"] == "sandbox"
    assert google.revoked == [REFRESH]
    assert GmailService(client.app.state.runtime).store(MAYA).get() is None
    assert "gmail.disconnected" in audit_text(data_dir)


def test_onboarding_inbox_step_accepts_gmail_once_connected(env):
    make, _, _ = env
    client = make()
    bid = client.post("/onboarding", json={"name": "Gmail Test Shop", "business_type": "fashion"}).json()["id"]
    step = f"/businesses/{bid}/onboarding/inbox"
    assert client.put(step, json={"connection": "gmail"}).status_code == 422
    url = client.post(f"/businesses/{bid}/connections/gmail/connect").json()["authorize_url"]
    state = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(url).query))["state"]
    assert client.get("/inbox/gmail/callback", params={"state": state, "code": "c"}).status_code == 200
    assert client.put(step, json={"connection": "gmail"}).json()["inbox"] == "gmail"


# ---- The planner never sees the token or the raw email ---------------------------------------------------------

def test_planner_sees_neither_token_nor_raw_email(env, attack):
    attack("ATK-GOAL-HIJACK-EMAIL", "real Gmail message and OAuth token kept away from the planner", "scripted")
    make, google, data_dir = env
    client = make()
    connect(client)
    google.new = ["18f0aaaa00000016"]
    client.post(f"{gm()}/poll")
    planner = FakeLLM(calls(("list_inbox", {})), text("One email is held."))
    client.app.state.runtime._llm = planner
    r = client.post(f"/businesses/{MAYA}/agent/ask", json={"message": "What's in my inbox?"})
    assert r.status_code == 200, r.text
    seen = json.dumps(planner.requests)
    assert "gm-18f0aaaa00000016" in seen  # the planner got the typed record...
    raw = google.mail["18f0aaaa00000016"].decode("utf-8", "replace")
    subject = next(line for line in raw.splitlines() if line.startswith("Subject:")).removeprefix("Subject:").strip()
    for secret in (REFRESH, ACCESS, "client-SECRET", ACCOUNT, subject):
        assert secret not in seen  # ...but no token, secret, account address or message text
    attack.caught("quarantine", "typed_fields_only")
