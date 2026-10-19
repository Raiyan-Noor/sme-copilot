"""The Morning brief tab's activity feed (GET /brief/activity): rows built from the overnight run's audit entries,
with their real (simulated-clock) times, and an Approve that goes through the same approval path as the Outbox and
the Payments tab. The feed itself only reads: it proposes, signs and executes nothing."""

import re
from pathlib import Path

import pytest

from tests.agent_env import build_template, copy_data_dir
from tests.api.test_api_demo_console import FakeExtractor
from tests.owner_api import approve
from tests.payments_env import MAYA, payments_env

GOLDEN_GRAIN = "item:MCS-SCH-0007"  # Golden Grain Wholesale invoice, due the day after the first fast-forward
FRONTEND = Path(__file__).resolve().parents[3] / "frontend"


@pytest.fixture(scope="module")
def template(tmp_path_factory):
    return build_template(tmp_path_factory.mktemp("brief-activity"))


@pytest.fixture
def env(template, tmp_path):
    data_dir, seed_dir = template
    pay = payments_env(copy_data_dir(data_dir, tmp_path / "tenants"), seed_dir, demo_mode=True)
    pay.rt._demo_llm = FakeExtractor()
    pay.connect()
    r = pay.app.post("/clock/advance", json={"days": 1})
    assert r.status_code == 200, r.text
    return pay


def feed(env) -> dict:
    r = env.app.get(env.url("/brief/activity"))
    assert r.status_code == 200, r.text
    return r.json()


def row(data: dict, row_id: str) -> dict:
    [found] = [r for r in data["rows"] if r["id"] == row_id]
    return found


def waiting_in_outbox(env) -> list[str]:
    return [w["approval_id"] for w in env.app.get(env.url("/outbox")).json()["waiting"]]


def test_every_row_time_is_the_time_of_a_real_audit_entry(env):
    entries = {e.seq: e for e in env.rt.audit.entries()}
    data = feed(env)
    assert data["brief_at"] and entries[data["brief_at"]["seq"]].kind == "brief.generated"
    kinds = {r["kind"] for r in data["rows"]}
    assert {"approval", "payment", "insight", "done"} <= kinds
    for r in data["rows"]:
        e = entries[r["at"]["seq"]]
        assert e.time and re.fullmatch(r"\d\d:\d\d:\d\d", e.time)
        assert (r["at"]["date"], r["at"]["time"]) == (e.date, e.time)
    assert [r["at"]["seq"] for r in data["rows"]] == sorted(r["at"]["seq"] for r in data["rows"])


def test_reading_the_feed_never_acts(env):
    feed(env)
    before = env.rt.audit.head()
    feed(env)
    after = env.rt.audit.entries()[before.seq + 1:]
    assert not [e.kind for e in after if e.kind.startswith(("gateway.", "executor.", "payments."))]


def test_approve_in_the_tab_uses_the_same_approval_handler_as_the_outbox(env):
    """The drafted reminders in the tab are the Outbox's waiting approvals, signed through the same gateway endpoint
    the approval sheet calls; the frontend has exactly one place that submits a signature."""
    emails = row(feed(env), "emails")
    assert emails["state"] == "waiting" and emails["approval_ids"]
    assert sorted(emails["approval_ids"]) == sorted(waiting_in_outbox(env))

    owner = env.enroll()
    for approval_id in emails["approval_ids"]:
        assert approve(env.app, MAYA, approval_id, owner)["status"] == "executed"

    done = row(feed(env), "emails")
    signed = [e for e in env.rt.audit.entries() if e.kind == "gateway.approval"]
    assert done["state"] == "done" and done["done_label"] == "Sent" and done["approval_ids"] == []
    assert (done["completed"]["seq"], done["completed"]["time"]) == (signed[-1].seq, signed[-1].time)
    assert waiting_in_outbox(env) == []

    # Frontend: the tab's Approve opens the Outbox's approval sheet (or the Outbox itself for a group) and the
    # Payments flow; only the approval sheet ever submits an approval's signature.
    tab = (FRONTEND / "components/advisor/brief-tab.tsx").read_text(encoding="utf-8")
    outbox = (FRONTEND / "components/advisor/panel-outbox.tsx").read_text(encoding="utf-8")
    payments = (FRONTEND / "components/advisor/panel-payments.tsx").read_text(encoding="utf-8")
    assert "openApproval({ approvalId" in tab and "openApproval({ approvalId" in outbox
    assert 'openPanel("outbox")' in tab
    assert 'from "./approve"' in tab and 'from "./approve"' in payments and "startPayment(" in payments
    submitters = sorted(p.name for p in (FRONTEND / "components").rglob("*.tsx")
                        if "api.approve(" in p.read_text(encoding="utf-8"))
    assert submitters == ["approval-sheet.tsx"]
    assert "api.approve(" not in tab and "signMessage(" not in tab


def test_a_supplier_payment_goes_through_the_payments_flow_and_the_gateway(env):
    pay = row(feed(env), "pay:MCS-SCH-0007")
    assert pay["state"] == "waiting" and pay["payment_key"] == GOLDEN_GRAIN and pay["approval_ids"] == []
    assert "Golden Grain Wholesale" in pay["detail"] and set(pay["facts"]) and not re.search(
        r"\d", re.sub(r"\{fact:[^}]+\}", "", pay["detail"]))

    request = env.create(source=GOLDEN_GRAIN)  # what the tab's Approve sends (startPayment)
    assert request["status"] == "awaiting_approval"
    waiting = row(feed(env), "pay:MCS-SCH-0007")
    assert waiting["payment_id"] == request["id"] and waiting["approval_ids"] == [request["approval_id"]]

    assert env.approve(request)["status"] == "executed"
    env.settle()
    paid = row(feed(env), "pay:MCS-SCH-0007")
    assert paid["state"] == "done" and paid["done_label"] in ("Paid", "Sent") and paid["completed"]["time"]


def test_a_refused_signature_shows_in_the_row(env):
    request = env.create(source=GOLDEN_GRAIN)
    env.enroll()
    r = env.app.post(env.url(f"/gateway/approvals/{request['approval_id']}/approve"),
                     json={"signature": "00" * 64, "public_key": env.owner.public_key})
    assert r.json()["status"] == "denied"
    refused = row(feed(env), "pay:MCS-SCH-0007")
    assert refused["state"] == "waiting" and refused["rule"] == "bad_signature"


def test_a_held_email_is_blocked_and_cannot_be_approved(env):
    r = env.app.post(env.url("/demo/send-preset"), json={"preset": "lookalike_phishing"})
    assert r.status_code == 200 and r.json()["verdict"] == "held", r.text
    email_id = r.json()["record"]["email_id"]
    held = row(feed(env), f"held:{email_id}")
    assert held["kind"] == "held" and held["state"] == "blocked" and held["flags"]
    assert held["approval_ids"] == [] and held["payment_key"] is None and held["payment_id"] is None
    assessed = [e for e in env.rt.audit.entries() if e.kind == "sentinel.assessed" and e.data["email_id"] == email_id]
    assert held["at"]["seq"] == assessed[-1].seq
