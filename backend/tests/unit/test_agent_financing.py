"""Planner financing tools end to end with a scripted LLM: match_financing and get_passport return only
placeholders, get_loan_application_draft prepares (never sends) a draft, and propose_action with it is held for the
owner's signature (invariants 1, 3, 4, 6)."""

import json
import re

import pytest

from tests.agent_env import MAYA, FakeLLM, agent_client, build_template, calls, copy_data_dir, text


@pytest.fixture(scope="module")
def template(tmp_path_factory):
    return build_template(tmp_path_factory.mktemp("agent_financing"))


@pytest.fixture
def client_llm(template, tmp_path):
    data_dir, seed_dir = template
    llm = FakeLLM()
    return agent_client(copy_data_dir(data_dir, tmp_path / "t"), seed_dir, llm), llm


def ask(client, message, conversation_id=None):
    body = {"message": message, **({"conversation_id": conversation_id} if conversation_id else {})}
    r = client.post(f"/businesses/{MAYA}/agent/ask", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def results(llm, request_index=-1):
    return [json.loads(m["content"]) for m in llm.requests[request_index] if m["role"] == "tool"]


def test_financing_tools_return_placeholders_only(client_llm):
    client, llm = client_llm
    llm.steps += [calls(("match_financing", {}), ("get_passport", {})), text("Done.")]
    ask(client, "Can I get a loan?")
    match, passport = results(llm)
    nano = next(p for p in match["products"] if p["product_id"] == "prd_nano")
    assert nano["status"] == "eligible" and nano["capped_by"] == "repayment_safety"
    assert nano["repayment_safe_amount"] == "{fact:financing.prd_nano.safe_amount}"
    digital = next(p for p in match["products"] if p["product_id"] == "prd_digital_line")
    rule = next(r for r in digital["rules"] if r["rule"] == "min_digital_history_months")
    assert rule["passed"] is False and rule["met_from_if_trading_continues"].startswith("{fact:")
    assert passport["band"] and passport["path_to_eligibility"]
    for result in (match, passport):
        flat = re.sub(r"\{fact:[^}]*\}", "", json.dumps(result))
        assert not re.search(r"\d", flat), flat


def test_draft_then_propose_is_held_for_the_owner(client_llm):
    client, llm = client_llm
    llm.steps += [calls(("get_loan_application_draft", {"product_id": "prd_nano"})),
                  text("I prepared a draft for {fact:financing.prd_nano.safe_amount}.")]
    first = ask(client, "Prepare the nano loan.")
    [draft] = results(llm)
    assert draft["status"] == "draft_saved_not_sent" and re.fullmatch(r"lad_[a-p]{24}", draft["draft_id"])

    propose = {"tool": "submit_loan_application",
               "args": {"product_id": "prd_nano", "draft_id": draft["draft_id"],
                        "amount_minor": {"fact": "financing.prd_nano.safe_amount"}},
               "reason": "Restock before the festival with {fact:financing.prd_nano.safe_amount}."}
    llm.steps += [calls(("propose_action", propose)), text("It is waiting for your signature.")]
    turn = ask(client, "Send it.", first["conversation_id"])
    seen = results(llm)[-1]
    assert seen == {"status": "pending_approval", "tool": "submit_loan_application",
                    "waiting_for": "owner_signature", "why": "tier_T3"}
    action = next(e for e in turn["events"] if e["type"] == "action")
    assert action["status"] == "pending_approval" and action["untrusted_args"] == []
    outbox = client.app.state.runtime.gateway(MAYA).executors.mailbox.outbox()
    assert outbox == []


def test_invented_draft_id_is_denied(client_llm):
    client, llm = client_llm
    llm.steps += [calls(("match_financing", {})), text("Checked.")]
    first = ask(client, "Loans?")
    propose = {"tool": "submit_loan_application",
               "args": {"product_id": "prd_nano", "draft_id": "lad_" + "b" * 24,
                        "amount_minor": {"fact": "financing.prd_nano.safe_amount"}},
               "reason": "Apply."}
    llm.steps += [calls(("propose_action", propose)), text("Denied.")]
    ask(client, "Apply now.", first["conversation_id"])
    seen = results(llm)[-1]
    assert seen == {"status": "denied", "tool": "submit_loan_application", "rule": "unknown_draft"}
