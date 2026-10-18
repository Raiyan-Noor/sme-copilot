"""LLM adapter: profile model choice, every fallback trigger, budget cap, record/replay, structured output and the
audit entry for each call (invariant 7). All providers are fakes; nothing touches the network."""

import json
from datetime import date

import pytest
from pydantic import BaseModel

from app.audit import AuditLog
from app.clock import FixedClock
from app.llm.adapter import SOL, TERRA, LLMAdapter, LLMOutputInvalid, LLMUnavailable
from app.llm.cache import ReplayMiss, RequestCache
from app.llm.spend import SpendTracker
from app.llm.types import Completion, ErrorKind, ProviderError, ToolCall, Usage

GEMINI = "gemini-2.5-flash"
MSGS = [{"role": "user", "content": "How many days of cash do we have? SECRET-CONTENT-MARKER"}]
OK = Completion(content="You have {fact:buffer_days} days.", finish_reason="stop",
                usage=Usage(input_tokens=1000, cached_input_tokens=200, output_tokens=100))


class FakeProvider:
    """Returns or raises the scripted items in order; the last item repeats. Records every call."""

    def __init__(self, name: str, *script):
        self.name = name
        self.script = list(script) or [OK]
        self.calls: list[tuple[str, dict]] = []

    def complete(self, model, request, timeout_s):
        self.calls.append((model, request))
        item = self.script[min(len(self.calls) - 1, len(self.script) - 1)]
        if isinstance(item, Exception):
            raise item
        return item


class Exploding:
    name = "openai"

    def complete(self, *a, **k):
        raise AssertionError("provider must not be called")


@pytest.fixture
def audit(tmp_path):
    return AuditLog(tmp_path / "audit.jsonl", FixedClock(date(2026, 10, 18)))


def make(tmp_path, audit, primary=None, fallback=None, *, mode="off", profile="dev", budget=7.0, spend=None,
         sleeps=None):
    return LLMAdapter(
        primary=primary, fallback=fallback, fallback_model=GEMINI,
        cache=RequestCache(tmp_path / "replay", mode), spend=spend or SpendTracker(tmp_path / "spend.json"),
        profile=profile, budget_usd=budget, audit=audit,
        sleep=(sleeps.append if sleeps is not None else lambda s: None),
    )


def llm_entries(audit, kind="llm.call"):
    return [e.data for e in audit.entries() if e.kind == kind]


# Profiles
@pytest.mark.parametrize("profile,role,model", [
    ("dev", "planner", TERRA), ("dev", "extractor", TERRA), ("demo", "planner", SOL),
    ("demo", "extractor", TERRA), ("demo", "brief_writer", SOL),
])
def test_profile_picks_model(tmp_path, audit, profile, role, model):
    openai_ = FakeProvider("openai")
    adapter = make(tmp_path, audit, openai_, FakeProvider("gemini"), profile=profile)
    result = adapter.chat(role, MSGS)
    assert openai_.calls[0][0] == model
    assert result.info.provider == "openai" and result.info.model == model


def test_primary_success_is_priced_and_logged(tmp_path, audit):
    adapter = make(tmp_path, audit, FakeProvider("openai"), FakeProvider("gemini"))
    result = adapter.chat("planner", MSGS)
    # Terra: 800 * 2.00 + 200 * 0.20 + 100 * 12.00 = 2840 micro-USD
    assert result.info.cost_microusd == 2840
    (entry,) = llm_entries(audit)
    assert entry["provider"] == "openai" and entry["model"] == TERRA
    assert (entry["input_tokens"], entry["cached_input_tokens"], entry["output_tokens"]) == (1000, 200, 100)
    assert entry["cost_microusd"] == 2840 and entry["cache"] == "off"
    assert entry["attempts"] == [{"provider": "openai", "model": TERRA, "outcome": "ok"}]
    assert result.info.audit_seq == 0
    assert adapter.spend.spent("openai") == 2840


# Fallback triggers
@pytest.mark.parametrize("kind", [ErrorKind.QUOTA, ErrorKind.RATE_LIMIT, ErrorKind.SERVER, ErrorKind.TIMEOUT,
                                  ErrorKind.CONNECTION])
def test_fallback_trigger(tmp_path, audit, kind):
    gemini = FakeProvider("gemini")
    adapter = make(tmp_path, audit, FakeProvider("openai", ProviderError(kind)), gemini)
    result = adapter.chat("planner", MSGS)
    assert result.info.provider == "gemini" and result.info.model == GEMINI
    assert gemini.calls[0][1]["messages"] == MSGS
    (entry,) = llm_entries(audit)
    assert entry["provider"] == "gemini"
    assert [a["outcome"] for a in entry["attempts"]] == [kind.value, "ok"]
    assert adapter.spend.spent("openai") == 0 and adapter.spend.spent("gemini") > 0


def test_budget_exhausted_skips_openai(tmp_path, audit):
    spend = SpendTracker(tmp_path / "spend.json")
    spend.add("openai", 7_000_000)
    adapter = make(tmp_path, audit, Exploding(), FakeProvider("gemini"), spend=spend)
    result = adapter.chat("planner", MSGS)
    assert result.info.provider == "gemini"
    assert llm_entries(audit)[0]["attempts"][0]["outcome"] == "budget_exhausted"


def test_call_that_crosses_the_cap_switches_the_next_call(tmp_path, audit):
    openai_, gemini = FakeProvider("openai"), FakeProvider("gemini")
    adapter = make(tmp_path, audit, openai_, gemini, budget=0.002)  # 2000 micro-USD; one call costs 2840
    assert adapter.chat("planner", MSGS).info.provider == "openai"
    assert adapter.budget_exhausted()
    assert adapter.chat("planner", MSGS + [{"role": "user", "content": "again"}]).info.provider == "gemini"
    assert len(openai_.calls) == 1


def test_budget_survives_restart(tmp_path, audit):
    make(tmp_path, audit, FakeProvider("openai"), budget=0.002).chat("planner", MSGS)
    restarted = make(tmp_path, audit, Exploding(), FakeProvider("gemini"), budget=0.002)
    assert restarted.budget_exhausted()
    assert restarted.chat("planner", MSGS).info.provider == "gemini"


def test_no_openai_key_goes_straight_to_gemini(tmp_path, audit):
    adapter = make(tmp_path, audit, None, FakeProvider("gemini"))
    assert adapter.chat("planner", MSGS).info.provider == "gemini"
    assert llm_entries(audit)[0]["attempts"][0]["outcome"] == "not_configured"


def test_bad_request_does_not_fall_back(tmp_path, audit):
    gemini = FakeProvider("gemini")
    adapter = make(tmp_path, audit, FakeProvider("openai", ProviderError(ErrorKind.BAD_REQUEST)), gemini)
    with pytest.raises(LLMUnavailable):
        adapter.chat("planner", MSGS)
    assert gemini.calls == []
    (failed,) = llm_entries(audit, "llm.call_failed")
    assert failed["attempts"][0]["outcome"] == "bad_request"


def test_gemini_429_is_retried_with_backoff(tmp_path, audit):
    sleeps = []
    gemini = FakeProvider("gemini", ProviderError(ErrorKind.RATE_LIMIT), ProviderError(ErrorKind.RATE_LIMIT), OK)
    adapter = make(tmp_path, audit, FakeProvider("openai", ProviderError(ErrorKind.QUOTA)), gemini, sleeps=sleeps)
    assert adapter.chat("planner", MSGS).info.provider == "gemini"
    assert sleeps == [1.0, 2.0]
    assert [a["outcome"] for a in llm_entries(audit)[0]["attempts"]] == [
        "insufficient_quota", "rate_limited", "rate_limited", "ok"]


def test_everything_down_raises_and_logs(tmp_path, audit):
    sleeps = []
    adapter = make(tmp_path, audit, FakeProvider("openai", ProviderError(ErrorKind.SERVER)),
                   FakeProvider("gemini", ProviderError(ErrorKind.RATE_LIMIT)), sleeps=sleeps)
    with pytest.raises(LLMUnavailable):
        adapter.chat("planner", MSGS)
    assert sleeps == [1.0, 2.0, 4.0]
    (failed,) = llm_entries(audit, "llm.call_failed")
    assert len(failed["attempts"]) == 5
    assert llm_entries(audit) == []


def test_gemini_server_error_is_not_retried(tmp_path, audit):
    gemini = FakeProvider("gemini", ProviderError(ErrorKind.SERVER))
    adapter = make(tmp_path, audit, None, gemini)
    with pytest.raises(LLMUnavailable):
        adapter.chat("planner", MSGS)
    assert len(gemini.calls) == 1


# Record / replay
def test_record_then_replay_without_providers(tmp_path, audit):
    recorder = make(tmp_path, audit, FakeProvider("openai"), mode="record")
    recorded = recorder.chat("planner", MSGS)
    assert recorded.info.cache == "miss"
    # Replay in another profile: the key is model-independent, so Sol replays what Terra recorded.
    replayer = make(tmp_path, audit, Exploding(), Exploding(), mode="replay", profile="demo")
    replayed = replayer.chat("planner", MSGS)
    assert replayed.content == recorded.content
    assert replayed.info.cache == "hit" and replayed.info.cost_microusd == 0
    assert replayed.info.provider == "openai" and replayed.info.model == TERRA  # who actually produced it
    assert replayed.info.request_key == recorded.info.request_key
    assert replayer.spend.spent("openai") == recorded.info.cost_microusd  # replay adds nothing


def test_record_mode_reuses_hits(tmp_path, audit):
    openai_ = FakeProvider("openai")
    adapter = make(tmp_path, audit, openai_, mode="record")
    adapter.chat("planner", MSGS)
    assert adapter.chat("planner", MSGS).info.cache == "hit"
    assert len(openai_.calls) == 1


def test_replay_miss_raises_and_never_calls(tmp_path, audit):
    adapter = make(tmp_path, audit, Exploding(), Exploding(), mode="replay")
    with pytest.raises(ReplayMiss):
        adapter.chat("planner", MSGS)
    assert len(llm_entries(audit, "llm.replay_miss")) == 1


def test_key_depends_on_role_and_tools(tmp_path, audit):
    adapter = make(tmp_path, audit, FakeProvider("openai"))
    tool = {"type": "function", "function": {"name": "get_cash", "parameters": {"type": "object"}}}
    keys = {
        adapter.chat("planner", MSGS).info.request_key,
        adapter.chat("brief_writer", MSGS).info.request_key,
        adapter.chat("planner", MSGS, tools=[tool]).info.request_key,
    }
    assert len(keys) == 3


# Tools and structured output
def test_tool_calls_round_trip(tmp_path, audit):
    reply = Completion(tool_calls=[ToolCall(id="c1", name="get_cash", arguments='{"as_of":"today"}')],
                       finish_reason="tool_calls", usage=Usage(input_tokens=10, output_tokens=5))
    tool = {"type": "function", "function": {"name": "get_cash", "parameters": {"type": "object"}}}
    openai_ = FakeProvider("openai", reply)
    result = make(tmp_path, audit, openai_).chat("planner", MSGS, tools=[tool], tool_choice="auto")
    assert openai_.calls[0][1]["tools"] == [tool]
    assert result.tool_calls[0].args() == {"as_of": "today"}
    assert result.assistant_message()["tool_calls"][0]["function"]["name"] == "get_cash"
    assert llm_entries(audit)[0]["tool_calls"] == ["get_cash"]


def test_extractor_cannot_have_tools(tmp_path, audit):
    tool = {"type": "function", "function": {"name": "x", "parameters": {"type": "object"}}}
    with pytest.raises(ValueError, match="invariant 2"):
        make(tmp_path, audit, Exploding()).chat("extractor", MSGS, tools=[tool])


class Invoice(BaseModel):
    payee_domain: str
    amount_minor: int
    due: str | None = None


def test_structured_output_validates(tmp_path, audit):
    reply = Completion(content='{"payee_domain":"acme.test","amount_minor":12500,"due":null}',
                       usage=Usage(input_tokens=50, output_tokens=20))
    openai_ = FakeProvider("openai", reply)
    result = make(tmp_path, audit, openai_).structured("extractor", MSGS, Invoice)
    assert result.data == Invoice(payee_domain="acme.test", amount_minor=12500)
    request = openai_.calls[0][1]
    assert "tools" not in request
    schema = request["response_format"]["json_schema"]
    assert schema["strict"] is True and schema["name"] == "Invoice"
    assert schema["schema"]["additionalProperties"] is False
    assert schema["schema"]["required"] == ["payee_domain", "amount_minor", "due"]


@pytest.mark.parametrize("content", ["not json", '{"payee_domain":"acme.test"}'])
def test_structured_output_rejects_bad_json(tmp_path, audit, content):
    adapter = make(tmp_path, audit, FakeProvider("openai", Completion(content=content)))
    with pytest.raises(LLMOutputInvalid):
        adapter.structured("extractor", MSGS, Invoice)
    assert len(llm_entries(audit, "llm.output_invalid")) == 1


# Audit hygiene
def test_audit_never_holds_message_content(tmp_path, audit):
    make(tmp_path, audit, FakeProvider("openai", ProviderError(ErrorKind.QUOTA)), FakeProvider("gemini")).chat(
        "planner", MSGS)
    text = (tmp_path / "audit.jsonl").read_text(encoding="utf-8")
    assert "SECRET-CONTENT-MARKER" not in text
    assert audit.verify().ok
    for line in text.splitlines():
        json.loads(line, parse_float=lambda s: pytest.fail(f"float in audit entry: {s}"))
