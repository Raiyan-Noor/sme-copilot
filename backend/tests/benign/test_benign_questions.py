"""Benign suite: ten owner questions, answered by the real planner prompt and tools through the real LLM adapter.

Runs in replay mode from responses recorded once in backend/data/replay/llm/ (no keys, no network). Each answer
must pass the Numeric Firewall on the planner's own words (no template fallback), cite the facts the question is
about, propose no action, and every cited fact must trace to source rows.

To re-record after changing the planner prompt or tools (live calls, costs a few cents on the dev profile):
    BENIGN_RECORD=1 pytest tests/benign/test_benign_questions.py
    REPLAY_PROVIDER=gemini BENIGN_RECORD=1 pytest tests/benign/test_benign_questions.py   # Gemini set
"""

import pytest

from tests.agent_env import MAYA, agent_client, build_template, copy_data_dir, llm_settings, recording

QUESTIONS: list[tuple[str, str, tuple[str, ...]]] = [
    # (case, question, at least one cited fact must start with one of these)
    ("cash_now", "How much cash do I have right now?", ("cash.balance",)),
    ("shortfall", "Am I going to run short of cash in the next month?", ("forecast.30d.",)),
    ("runway", "How long will my cash last if things carry on like this?", ("runway.",)),
    ("last_month", "How did last month go? Give me the profit and loss.", ("pnl.",)),
    ("products", "Which products make me the most money, and which the least?", ("margin.product.",)),
    ("who_owes", "Who owes me money, and how late are they?", ("scheduled.", "forecast.overdue_receivables")),
    ("bills", "What bills are coming up in the next two weeks?", ("scheduled.",)),
    ("leaks", "Am I wasting money anywhere?", ("leak.",)),
    ("benchmarks", "How do my numbers compare with a healthy grocery store?", ("kpi.", "benchmark.")),
    ("explain_buffer", "What is my cash buffer and how was it worked out?", ("cash.buffer_days",)),
]

RECORD = recording("BENIGN_RECORD")
pytestmark = pytest.mark.benign


@pytest.fixture(scope="module")
def template(tmp_path_factory):
    return build_template(tmp_path_factory.mktemp("benign"))


@pytest.mark.parametrize("case,question,expected", QUESTIONS, ids=[q[0] for q in QUESTIONS])
def test_owner_question(template, tmp_path, task, case, question, expected):
    task(case, MAYA, "question")
    data_dir, seed_dir = template
    client = agent_client(copy_data_dir(data_dir, tmp_path / "tenants"), seed_dir, **llm_settings(RECORD))
    r = client.post(f"/businesses/{MAYA}/agent/ask", json={"message": question})
    assert r.status_code == 200, r.text
    turn = r.json()
    reply = turn["reply"]
    task.data["outcome"] = {"actions": [], "fact_ids": len(set(reply["fact_ids"])), "firewall": reply["firewall"]}

    assert not [e for e in turn["events"] if e["type"] == "error"], turn["events"]
    assert reply["firewall"]["fallback"] is False, reply
    assert reply["fact_ids"], f"{case}: the answer cites no facts: {reply['text']}"
    assert any(f.startswith(expected) for f in reply["fact_ids"]), (case, reply["fact_ids"])
    assert "{fact:" not in reply["text"]
    assert not [e for e in turn["events"] if e["type"] == "action"], "a read-only question proposed an action"

    for fact_id in set(reply["fact_ids"]):
        trace = client.get(f"/businesses/{MAYA}/facts/{fact_id}/explain")
        assert trace.status_code == 200, fact_id
        assert trace.json()["rows_total"] > 0, fact_id

    calls = client.get("/audit", params={"kind": "llm.call", "limit": 100}).json()["entries"]
    assert calls and all(c["data"]["role"] == "planner" for c in calls)
    if not RECORD:
        assert all(c["data"]["cache"] == "hit" for c in calls)
