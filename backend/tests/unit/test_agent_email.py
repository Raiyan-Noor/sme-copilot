"""The planner drafting an email through propose_action (scripted LLM, real gateway): the text is rendered through the
Numeric Firewall into a stored draft, the gateway sees only a recipient and a draft ID, and the owner's signature
sends it. Also the overnight reminder draft end to end, through the owner's approval route and the outbox API."""

import json

import pytest

from tests.agent_env import MAYA, FakeLLM, agent_client, build_template, calls, copy_data_dir, text
from tests.owner_api import approve, enroll

AMOUNT = "scheduled.mcs-sch-0003.amount"
DUE = "scheduled.mcs-sch-0003.due_date"
LISTED = ("list_receivables", {"only_overdue": True})


@pytest.fixture(scope="module")
def template(tmp_path_factory):
    return build_template(tmp_path_factory.mktemp("agent-email"))


@pytest.fixture
def make_client(template, tmp_path):
    data_dir, seed_dir = template

    def make(*steps):
        llm = FakeLLM(*steps)
        client = agent_client(copy_data_dir(data_dir, tmp_path / f"t{len(list(tmp_path.iterdir()))}"), seed_dir, llm)
        return client, llm

    return make


def email(recipient="cus_greenleaf", subject="Your open invoice", body=None, reason="It is overdue."):
    body = body if body is not None else f"Hello, your invoice for {{fact:{AMOUNT}}} was due on {{fact:{DUE}}}. Thank you."
    return ("propose_action", {"tool": "send_email", "reason": reason,
                               "args": {"recipient_id": recipient, "subject": subject, "body": body}})


def ask(client, message="Email Greenleaf about the overdue invoice."):
    r = client.post(f"/businesses/{MAYA}/agent/ask", json={"message": message})
    assert r.status_code == 200, r.text
    return r.json()


def last_result(llm):
    return [json.loads(m["content"]) for m in llm.requests[-1] if m["role"] == "tool"][-1]


def audit(client, kind):
    return client.get("/audit", params={"kind": kind, "limit": 500}).json()["entries"]


def pending_emails(client):
    return client.get(f"/businesses/{MAYA}/outbox").json()["waiting"]


def test_the_planner_drafts_an_email_that_waits_for_the_owner(make_client):
    client, llm = make_client(calls(LISTED), calls(email()), text("The email is waiting for your signature."))
    turn = ask(client)
    [action] = [e for e in turn["events"] if e["type"] == "action"]
    assert action["status"] == "pending_approval" and action["untrusted_args"] == []
    assert last_result(llm) == {"status": "pending_approval", "tool": "send_email", "waiting_for": "owner_signature",
                                "why": "tier_T3"}
    [waiting] = pending_emails(client)
    mail = waiting["email"]
    assert mail["recipient_id"] == "cus_greenleaf" and mail["origin"] == "planner"
    assert mail["subject"] == "Your open invoice"
    assert "$214.00" in mail["body"] and "{fact:" not in mail["body"]  # rendered from the cited fact
    assert mail["fact_ids"] == [AMOUNT, DUE]
    assert client.get(f"/businesses/{MAYA}/outbox").json()["sent"] == []
    [decision] = audit(client, "gateway.decision")
    assert set(decision["data"]["args"]) == {"recipient_id", "draft_id"}  # the gateway never sees free text
    assert audit(client, "email.drafted")


def test_the_owner_reads_signs_and_the_email_lands_in_the_outbox(make_client):
    client, _ = make_client(calls(LISTED), calls(email()), text("Waiting for your signature."))
    ask(client)
    [waiting] = pending_emails(client)
    owner = enroll(client, MAYA)
    view = client.get(f"/businesses/{MAYA}/gateway/approvals/{waiting['approval_id']}").json()
    assert view["email"]["body"] == waiting["email"]["body"] and view["tool"] == "send_email"
    done = approve(client, MAYA, waiting["approval_id"], owner)
    assert done["status"] == "executed" and done["result"]["transport"] == "sandbox"
    out = client.get(f"/businesses/{MAYA}/outbox").json()
    assert out["waiting"] == []
    [sent] = out["sent"]
    assert sent["subject"] == "Your open invoice" and "$214.00" in sent["body"] and sent["origin"] == "planner"
    assert sent["recipient_name"] and sent["ref"].startswith("sbx_mail_") and sent["transport"] == "sandbox"
    executed = audit(client, "executor.executed")[-1]["data"]["result"]
    assert "body" not in executed and executed["draft_sha256"] == waiting["email"]["sha256"]


def test_a_number_the_planner_invents_never_becomes_an_email(make_client):
    steps = [calls(LISTED),
             calls(email(body="Please pay 214 dollars by the 5th.")),  # digits outside a placeholder
             calls(email(body="Please pay {fact:made.up} now.")),  # a fact no tool returned
             calls(email(subject="Invoice 4412 overdue")),  # digits in the subject
             text("I could not write it.")]
    client, llm = make_client(*steps)
    ask(client)
    for request in llm.requests[2:5]:
        assert "Numeric Firewall" in json.loads([m for m in request if m["role"] == "tool"][-1]["content"])["error"]
    assert pending_emails(client) == [] and audit(client, "email.drafted") == []
    assert audit(client, "gateway.decision") == []


def test_the_planner_can_retry_after_a_rejected_email(make_client):
    client, _ = make_client(calls(LISTED), calls(email(body="Pay 214 now.")), calls(email()), text("Done."))
    ask(client)
    assert len(pending_emails(client)) == 1


def test_a_recipient_the_planner_was_not_given_is_denied(make_client):
    client, llm = make_client(calls(LISTED), calls(email(recipient="cus_stranger")), text("Not sent."))
    [action] = [e for e in ask(client)["events"] if e["type"] == "action"]
    assert (action["status"], action["rule"]) == ("denied", "untrusted_args_denied")
    assert last_result(llm) == {"status": "denied", "tool": "send_email", "rule": "untrusted_args_denied"}
    assert pending_emails(client) == []


def test_a_fact_from_quarantined_content_makes_the_draft_untrusted(make_client, template):
    """An amount the extractor read from an email is untrusted (invariant 3); an email that cites it is denied."""
    client, llm = make_client(calls(LISTED), calls(email(body="Hello, you owe {fact:scheduled.mail-inv-one.amount}.")),
                              text("Not sent."))
    with client.app.state.runtime.business(MAYA) as conn, conn:
        conn.execute("INSERT INTO scheduled_items (id, kind, category, due_date, amount_minor, status,"
                     " counterparty_id, reference, source) VALUES ('MAIL-INV-ONE', 'receivable', 'customer_invoice',"
                     " '2026-10-01', 9900, 'open', 'cus_greenleaf', NULL, 'mailbox')")
    [action] = [e for e in ask(client)["events"] if e["type"] == "action"]
    assert action["status"] == "denied" and action["rule"] == "untrusted_args_denied"
    assert pending_emails(client) == []


def test_the_planner_cannot_reach_the_gateway_with_free_text_arguments(make_client):
    steps = [calls(LISTED), calls(("propose_action", {"tool": "send_email", "reason": "Overdue.",
                                                      "args": {"recipient_id": "cus_greenleaf"}})),
             text("Not sent.")]
    client, llm = make_client(*steps)
    ask(client)
    assert "subject and body" in last_result(llm)["error"]
    assert pending_emails(client) == []


def test_the_owner_can_edit_the_draft_before_signing(make_client):
    client, _ = make_client(calls(LISTED), calls(email()), text("Waiting."))
    ask(client)
    [waiting] = pending_emails(client)
    owner = enroll(client, MAYA)
    old = waiting["approval_id"]
    r = client.post(f"/businesses/{MAYA}/gateway/approvals/{old}/revise-email",
                    json={"subject": "Quick note", "body": "Hi, could you settle the invoice this week? Thanks."})
    assert r.status_code == 200 and r.json()["status"] == "pending_approval"
    new = r.json()["approval"]["approval_id"]
    assert approve(client, MAYA, old, owner)["status"] == "denied"
    assert approve(client, MAYA, new, owner)["status"] == "executed"
    [sent] = client.get(f"/businesses/{MAYA}/outbox").json()["sent"]
    assert sent["subject"] == "Quick note" and sent["body"].startswith("Hi, could you settle")


def test_declining_over_the_api_closes_the_approval(make_client):
    client, _ = make_client(calls(LISTED), calls(email()), text("Waiting."))
    ask(client)
    [waiting] = pending_emails(client)
    owner = enroll(client, MAYA)
    assert client.post(f"/businesses/{MAYA}/gateway/approvals/{waiting['approval_id']}/decline").json() == {
        "declined": True}
    assert approve(client, MAYA, waiting["approval_id"], owner)["status"] == "denied"
    out = client.get(f"/businesses/{MAYA}/outbox").json()
    assert out["sent"] == [] and out["waiting"] == []


def test_a_new_address_needs_the_extra_confirmation(make_client):
    client, _ = make_client()
    base = f"/businesses/{MAYA}/emails"
    body = {"name": "Dana Reed", "email": "dana@reed-foods.example", "confirm_email": "dana@reed-foods.example",
            "confirmed": True}
    assert client.post(f"{base}/recipients", json={**body, "confirmed": False}).status_code == 422
    assert client.post(f"{base}/recipients", json={**body, "confirm_email": "dana@other.example"}).status_code == 422
    assert client.post(f"{base}/recipients", json={**body, "email": "nope", "confirm_email": "nope"}).status_code == 422
    r = client.post(f"{base}/recipients", json=body)
    assert r.status_code == 200 and r.json()["kind"] == "added" and r.json()["id"].startswith("rcp_")
    contacts = client.get(f"{base}/contacts").json()
    assert any(c["id"] == r.json()["id"] and c["kind"] == "added" for c in contacts)
    assert any(c["kind"] == "customer" for c in contacts)
    # The owner writes to the new address: a draft and a pending approval, never a send.
    d = client.post(f"{base}/draft", json={"recipient_id": r.json()["id"], "subject": "Hello", "body": "Nice to meet you."})
    assert d.status_code == 200 and d.json()["status"] == "pending_approval"
    [waiting] = client.get(f"/businesses/{MAYA}/outbox").json()["waiting"]
    assert waiting["email"]["added_by_owner"] is True and waiting["email"]["origin"] == "owner"


def test_the_owner_cannot_email_a_stranger_or_use_placeholders(make_client):
    client, _ = make_client()
    base = f"/businesses/{MAYA}/emails/draft"
    d = client.post(base, json={"recipient_id": "cus_stranger", "subject": "Hi", "body": "Hello."})
    assert d.json()["status"] == "denied" and d.json()["rule"] == "unknown_recipient"
    assert client.post(base, json={"recipient_id": "cus_greenleaf", "subject": "Hi",
                                   "body": "You owe {fact:cash.balance}."}).status_code == 422
