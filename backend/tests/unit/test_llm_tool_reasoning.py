"""Chat calls with function tools ask for reasoning_effort "none": Chat Completions rejects tools combined with
reasoning on the GPT-5.6 models with HTTP 400, which would leave the planner unable to call any tool."""

from datetime import date

from app.audit import AuditLog
from app.clock import FixedClock
from app.llm.adapter import LLMAdapter, OpenAICompatProvider
from app.llm.cache import RequestCache
from app.llm.spend import SpendTracker
from tests.unit.test_llm_adapter import MSGS, FakeProvider

TOOLS = [{"type": "function", "function": {"name": "get_cash_position", "parameters": {"type": "object"}}}]


def _adapter(tmp_path, primary):
    return LLMAdapter(primary=primary, fallback=None, fallback_model="gemini-2.5-flash",
                      cache=RequestCache(tmp_path / "replay", "off"), spend=SpendTracker(tmp_path / "spend.json"),
                      audit=AuditLog(tmp_path / "audit.jsonl", FixedClock(date(2026, 10, 18))))


def test_tool_calls_turn_reasoning_off(tmp_path):
    provider = FakeProvider("openai")
    _adapter(tmp_path, provider).chat("planner", MSGS, tools=TOOLS)
    assert provider.calls[0][1]["reasoning_effort"] == "none"


def test_chat_without_tools_leaves_reasoning_alone(tmp_path):
    provider = FakeProvider("openai")
    _adapter(tmp_path, provider).chat("planner", MSGS)
    assert "reasoning_effort" not in provider.calls[0][1]


def test_provider_forwards_reasoning_effort():
    sent = {}

    class Completions:
        def create(self, **kwargs):
            sent.update(kwargs)
            raise RuntimeError("stop before the network")

    provider = OpenAICompatProvider("openai", "sk-test")
    provider._client = type("C", (), {"chat": type("Chat", (), {"completions": Completions()})()})()
    try:
        provider.complete("gpt-5.6-terra", {"messages": MSGS, "tools": TOOLS, "reasoning_effort": "none"}, 5)
    except RuntimeError:
        pass
    assert sent["reasoning_effort"] == "none" and sent["tools"] == TOOLS
