"""Planner loop with a scripted LLM, end to end through /agent/ask and /agent/chat.

Covers the Numeric Firewall on replies (accept, one re-prompt, template fallback), propose_action (statuses straight
from the gateway, fact-only amounts, provenance, Tier 4 requests) and the audit trail of a turn.
"""

import json
import re
from datetime import timedelta

import pytest

from app.agent.tools import READ_TOOLS
from app.gateway import SignedPayload, StandingTerms, load_policy
from app.llm.cache import ReplayMiss
from tests.agent_env import MAYA, FakeLLM, agent_client, build_template, calls, copy_data_dir, text
from tests.gateway_env import Owner

GREENLEAF_INVOICE = "MCS-SCH-0003"  # open, overdue, below the T2 cap
GREENLEAF_AMOUNT = "scheduled.mcs-sch-0003.amount"


@pytest.fixture(scope="module")
def template(tmp_path_factory):
    return build_template(tmp_path_factory.mktemp("agent"))


@pytest.fixture
def make_client(template, tmp_path):
    data_dir, seed_dir = template

    def make(*steps):
        llm = FakeLLM(*steps)
        client = agent_client(copy_data_dir(data_dir, tmp_path / f"t{len(list(tmp_path.iterdir()))}"), seed_dir, llm)
        return client, llm
    return make


def ask(client, message="How much cash do I have?", conversation_id=None):
    body = {"message": message, **({"conversation_id": conversation_id} if conversation_id else {})}
    r = client.post(f"/businesses/{MAYA}/agent/ask", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def audit(client, kind):
    return client.get("/audit", params={"kind": kind, "limit": 500}).json()["entries"]


def tool_results(llm, request_index=-1):
    return [json.loads(m["content"]) for m in llm.requests[request_index] if m["role"] == "tool"]


# Replies and the Numeric Firewall --------------------------------------------------------------------------------

def test_reply_with_cited_facts_is_rendered(make_client):
    client, _ = make_client(calls(("get_cash_position", {})),
                            text("You have {fact:cash.balance} in the bank, a buffer of {fact:cash.buffer_days}."))
    turn = ask(client)
    reply = turn["reply"]
    assert reply["firewall"] == {"attempts": 1, "rejected": [], "fallback": False}
    assert reply["fact_ids"] == ["cash.balance", "cash.buffer_days"]
    assert "{fact:" not in reply["text"] and "$" in reply["text"]
    linked = [s for s in reply["segments"] if s["fact_id"]]
    assert [s["fact_id"] for s in linked] == ["cash.balance", "cash.buffer_days"]
    assert [e["type"] for e in turn["events"]] == ["conversation", "tool_call", "reply"]
    assert re.fullmatch(r"conv_[a-z]{16}", turn["conversation_id"])


def test_read_tool_results_never_carry_raw_numbers(make_client):
    steps = [calls(*[(t.name, {"fact_id": "cash.balance"} if t.name == "explain_fact" else {}) for t in READ_TOOLS
                     if t.name != "explain_fact"]),
             calls(("explain_fact", {"fact_id": "cash.buffer_days"})),
             text("Done.")]
    client, llm = make_client(*steps)
    ask(client)
    for result in tool_results(llm):
        assert "error" not in result, result
        flat = re.sub(r"\{fact:[^}]*\}", "", json.dumps(result))
        flat = re.sub(r'"(invoice_id|bill_id|product_id)": "[^"]*"', "", flat)
        assert not re.search(r"\d", flat), flat


def test_digit_in_reply_gets_one_reprompt(make_client):
    client, llm = make_client(calls(("get_cash_position", {})),
                              text("You have about $15,800 in cash."),
                              text("You have {fact:cash.balance} in cash."))
    reply = ask(client)["reply"]
    assert reply["firewall"] == {"attempts": 2, "rejected": [["digit"]], "fallback": False}
    assert reply["fact_ids"] == ["cash.balance"]
    correction = llm.requests[-1][-1]
    assert correction["role"] == "user" and correction["content"].startswith("[Numeric Firewall]")
    assert [e["data"]["violations"] for e in audit(client, "agent.firewall_rejected")] == [["digit"]]


def test_second_violation_falls_back_to_template(make_client):
    client, llm = make_client(calls(("get_cash_position", {})),
                              text("Cash: 15837.53"),
                              text("Cash is {fact:cash.balance}, so roughly 2 weeks of spending."))
    reply = ask(client)["reply"]
    assert reply["firewall"]["fallback"] is True and reply["firewall"]["rejected"] == [["digit"], ["digit"]]
    assert reply["text"].startswith("I couldn't word that answer safely.")
    assert "roughly" not in reply["text"]  # none of the planner's words reach the owner
    assert "cash.balance" in reply["fact_ids"]
    assert audit(client, "agent.reply")[-1]["data"]["fallback"] is True


def test_unknown_fact_is_rejected(make_client):
    client, llm = make_client(text("Your runway is {fact:runway.days}."),  # cited without calling a tool
                              text("Your runway is {fact:runway.days}."))
    reply = ask(client)["reply"]
    assert reply["firewall"]["rejected"] == [["unknown_fact"], ["unknown_fact"]]
    assert reply["firewall"]["fallback"] is True
    assert "runway.days" in llm.requests[-1][-1]["content"]


@pytest.mark.parametrize("smuggled", ["١٥٨٣٧ in cash", "Cash ⑮ days", "{fact:1500}", "{ fact:cash.balance }"])
def test_smuggled_numbers_are_rejected(make_client, smuggled):
    client, _ = make_client(calls(("get_cash_position", {})), text(smuggled), text(smuggled))
    assert ask(client)["reply"]["firewall"]["fallback"] is True


def test_llm_unavailable_falls_back(make_client):
    client, _ = make_client(ReplayMiss("llm", "abc"))
    turn = ask(client)
    assert [e["type"] for e in turn["events"]] == ["conversation", "error", "reply"]
    assert turn["events"][1]["kind"] == "replay_miss"
    assert turn["reply"]["text"].startswith("I can't reach the assistant right now.")


def test_step_limit_falls_back(make_client):
    client, _ = make_client(*[calls(("get_runway", {}))] * 8)
    turn = ask(client)
    assert any(e["type"] == "error" and e["kind"] == "step_limit" for e in turn["events"])
    assert turn["reply"]["firewall"]["fallback"] is True and "runway.days" in turn["reply"]["fact_ids"]


def test_rejected_drafts_stay_out_of_history(make_client):
    client, llm = make_client(calls(("get_cash_position", {})), text("Cash: 15837"), text("Cash: {fact:cash.balance}."),
                              text("Still {fact:cash.balance}."))
    first = ask(client)
    second = ask(client, "And now?", first["conversation_id"])
    assert second["reply"]["fact_ids"] == ["cash.balance"]  # cited from the earlier turn's tool result
    history = llm.requests[-1]
    assert not any("15837" in (m.get("content") or "") for m in history)
    assert [m["role"] for m in history] == ["system", "user", "assistant", "tool", "assistant", "user"]


def test_system_prompt_is_filled_without_digits(make_client):
    client, llm = make_client(text("Hello."))
    ask(client)
    system = llm.requests[0][0]["content"]
    assert "Maya's Corner Store" in system and "Maya Collins" in system and "{fact:clock.today}" in system
    assert "{{" not in system and "<!--" not in system


# propose_action ----------------------------------------------------------------------------------------------------

def _grant_reminders(client, allowlist=("cus_greenleaf",)):
    rt = client.app.state.runtime
    gw, owner = rt.gateway(MAYA), Owner()
    gw.enroll_owner_key(owner.public_key)
    terms = StandingTerms(max_amount_minor=50000, allowlist=allowlist)
    payload = SignedPayload(action="send_invoice_reminder", args_hash=terms.hash(), nonce="n" * 32,
                            expiry=rt.clock.today() + timedelta(days=30))
    assert gw.register_standing_mandate(payload, terms, owner.sign(payload), owner.public_key).accepted


def _remind(customer="cus_greenleaf", invoice=GREENLEAF_INVOICE, amount=None, reason="Greenleaf is overdue."):
    return ("propose_action", {"tool": "send_invoice_reminder", "reason": reason, "args": {
        "customer_id": customer, "invoice_id": invoice,
        "invoice_amount_minor": amount if amount is not None else {"fact": GREENLEAF_AMOUNT}}})


def _actions(turn):
    return [e for e in turn["events"] if e["type"] == "action"]


def test_t2_reminder_executes_under_a_mandate(make_client):
    client, llm = make_client(calls(("list_receivables", {"only_overdue": True})), calls(_remind()),
                              text("Sent a reminder to Greenleaf for {fact:" + GREENLEAF_AMOUNT + "}."))
    _grant_reminders(client)
    turn = ask(client, "Remind Greenleaf.")
    [action] = _actions(turn)
    assert action["status"] == "executed" and action["untrusted_args"] == []
    assert tool_results(llm)[-1] == {"status": "executed", "tool": "send_invoice_reminder"}
    [decision] = audit(client, "gateway.decision")
    assert decision["data"]["args"]["invoice_amount_minor"] == 21400  # the fact's value, put there by code
    assert audit(client, "executor.executed")


def test_t2_without_mandate_is_denied_with_rule(make_client):
    client, llm = make_client(calls(("list_receivables", {})), calls(_remind()), text("Not sent."))
    [action] = _actions(ask(client))
    assert (action["status"], action["rule"]) == ("denied", "no_standing_mandate")
    assert tool_results(llm)[-1] == {"status": "denied", "tool": "send_invoice_reminder",
                                     "rule": "no_standing_mandate"}


def test_literal_amount_is_refused_before_the_gateway(make_client):
    client, llm = make_client(calls(("list_receivables", {})), calls(_remind(amount=21400)), text("Not sent."))
    _grant_reminders(client)
    turn = ask(client)
    assert _actions(turn) == []
    assert "never as a number" in tool_results(llm)[-1]["error"]
    assert audit(client, "gateway.decision") == []


def test_values_the_planner_was_not_given_are_untrusted(make_client):
    # The customer ID never appeared in a tool result, so it counts as untrusted and forces owner approval.
    client, llm = make_client(calls(("list_receivables", {})), calls(_remind(customer="cus_attacker")),
                              text("Waiting for your signature."))
    _grant_reminders(client, allowlist=("cus_greenleaf", "cus_attacker"))
    [action] = _actions(ask(client))
    assert action["status"] == "pending_approval" and action["untrusted_args"] == ["customer_id"]
    assert action["approval_id"].startswith("apr_")
    seen = tool_results(llm)[-1]
    assert seen["status"] == "pending_approval" and "approval_id" not in json.dumps(seen)


def test_scheduled_item_from_an_email_forces_approval(make_client):
    # A due date the extractor read from an email: its IDs and amount are untrusted (invariant 3), so even an
    # allow-listed customer under a valid T2 mandate needs the owner's signature.
    client, llm = make_client(calls(("list_receivables", {})),
                              calls(_remind(invoice="MAIL-INV-ONE", amount={"fact": "scheduled.mail-inv-one.amount"})),
                              text("Waiting for your signature."))
    _grant_reminders(client)
    with client.app.state.runtime.business(MAYA) as conn, conn:
        conn.execute("INSERT INTO scheduled_items (id, kind, category, due_date, amount_minor, status,"
                     " counterparty_id, reference, source) VALUES ('MAIL-INV-ONE', 'receivable', 'customer_invoice',"
                     " '2026-10-01', 9900, 'open', 'cus_greenleaf', NULL, 'mailbox')")
    turn = ask(client)
    listed = [i for i in tool_results(llm, -1)[0]["invoices"] if i["invoice_id"] == "MAIL-INV-ONE"]
    assert listed and listed[0]["provenance"] == "untrusted"
    [action] = _actions(turn)
    assert action["status"] == "pending_approval"
    # The customer was named by untrusted content too, so it stays untrusted for the rest of the conversation.
    assert action["untrusted_args"] == ["customer_id", "invoice_amount_minor", "invoice_id"]


def test_fact_not_from_a_tool_is_refused(make_client):
    client, llm = make_client(calls(_remind()), text("Not sent."))
    ask(client)
    assert "did not come from a tool result" in tool_results(llm)[-1]["error"]


def test_reason_must_pass_the_firewall(make_client):
    client, llm = make_client(calls(("list_receivables", {})), calls(_remind(reason="It is 41 days late.")),
                              text("Not sent."))
    _grant_reminders(client)
    ask(client)
    assert "Numeric Firewall" in tool_results(llm)[-1]["error"]
    assert audit(client, "gateway.decision") == []


def test_reason_is_rendered_for_the_owner(make_client):
    reason = "Greenleaf owes {fact:" + GREENLEAF_AMOUNT + "}."
    client, _ = make_client(calls(("list_receivables", {})), calls(_remind(reason=reason)), text("Sent."))
    _grant_reminders(client)
    [action] = _actions(ask(client))
    assert action["reason"] == "Greenleaf owes $214.00."
    assert [s["fact_id"] for s in action["reason_segments"] if s["fact_id"]] == [GREENLEAF_AMOUNT]


def test_tier4_request_is_denied_and_logged_as_violation(make_client):
    client, llm = make_client(calls(("propose_action", {"tool": "change_prices", "args": {"product_id": "MILK-1L"},
                                                        "reason": "Raise milk prices."})),
                              text("I can't change prices; that decision stays with you."))
    [action] = _actions(ask(client, "Raise my milk price."))
    assert (action["status"], action["rule"]) == ("denied", "unknown_tool")
    assert [e["data"]["rule"] for e in audit(client, "gateway.violation")] == ["unknown_tool"]


def test_unknown_tool_name_is_an_error(make_client):
    client, llm = make_client(calls(("pay_supplier_now", {})), text("I can't do that."))
    ask(client)
    assert "no tool named" in tool_results(llm)[-1]["error"]


# Registry and audit -----------------------------------------------------------------------------------------------

def test_read_tools_are_all_tier1_in_policy():
    policy = load_policy()
    for tool in READ_TOOLS:
        assert policy.tier_of(tool.name) == "T1", tool.name
    names = {t.name for t in READ_TOOLS}
    assert not names & (set(policy.t2) | set(policy.t3) | set(policy.system_tools))


def test_turn_is_audited(make_client):
    client, _ = make_client(calls(("get_cash_position", {})), text("You have {fact:cash.balance}."))
    turn = ask(client, "How much cash?")
    started = audit(client, "agent.turn_started")[-1]["data"]
    assert started["conversation_id"] == turn["conversation_id"] and "How much" not in json.dumps(started)
    [call] = audit(client, "agent.tool_call")
    assert call["data"]["tool"] == "get_cash_position" and "cash.balance" in call["data"]["fact_ids"]
    assert audit(client, "agent.reply")[-1]["data"]["fact_ids"] == ["cash.balance"]
    assert client.get("/audit/verify").json()["ok"] is True


def test_reply_facts_trace_to_source_rows(make_client):
    client, _ = make_client(calls(("list_leaks", {}), ("list_receivables", {})), text("Done."))
    turn = ask(client)
    cited = [f for e in turn["events"] if e["type"] == "tool_call" for f in e["fact_ids"]]
    assert any(f.startswith("leak.") for f in cited) and any(f.startswith("scheduled.") for f in cited)
    for fact_id in cited:
        trace = client.get(f"/businesses/{MAYA}/facts/{fact_id}/explain")
        assert trace.status_code == 200 and trace.json()["rows_total"] > 0, fact_id


# SSE --------------------------------------------------------------------------------------------------------------

def test_chat_streams_server_sent_events(make_client):
    client, _ = make_client(calls(("get_runway", {})), text("Cash lasts {fact:runway.days}."))
    with client.stream("POST", f"/businesses/{MAYA}/agent/chat", json={"message": "Runway?"}) as r:
        assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
        body = "".join(r.iter_text())
    events = [(m[1], json.loads(m[2])) for m in re.finditer(r"event: (\w+)\ndata: (.*)\n\n", body)]
    assert [name for name, _ in events] == ["conversation", "tool_call", "reply", "done"]
    assert events[2][1]["fact_ids"] == ["runway.days"]
    assert events[3][1]["conversation_id"] == events[0][1]["conversation_id"]


def test_unknown_business_is_404_before_streaming(make_client):
    client, _ = make_client()
    assert client.post("/businesses/nope/agent/chat", json={"message": "hi"}).status_code == 404


def test_bad_conversation_id_is_rejected(make_client):
    client, _ = make_client()
    r = client.post(f"/businesses/{MAYA}/agent/ask", json={"message": "hi", "conversation_id": "conv_1; drop"})
    assert r.status_code == 422
