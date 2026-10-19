"""The real OpenAI-compatible provider over a mocked HTTP transport: the SDK's own exceptions are mapped to the
error kinds that drive fallback, and responses (content, tool calls, usage) are normalized. No network."""

import json

import httpx
import pytest

from app.llm.adapter import OpenAICompatProvider
from app.llm.types import ErrorKind, ProviderError

REQ = {"messages": [{"role": "user", "content": "hi"}], "max_output_tokens": 50}


def provider(handler, **kw) -> OpenAICompatProvider:
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return OpenAICompatProvider("openai", "sk-test", base_url="https://llm.test/v1", http_client=client, **kw)


def error(status, code=None, type_=None):
    body = {"error": {"message": "nope", "type": type_, "code": code}}
    return lambda request: httpx.Response(status, json=body)


@pytest.mark.parametrize("handler,kind", [
    (error(429, code="insufficient_quota", type_="insufficient_quota"), ErrorKind.QUOTA),
    (error(429, code="rate_limit_exceeded"), ErrorKind.RATE_LIMIT),
    (error(500), ErrorKind.SERVER),
    (error(503), ErrorKind.SERVER),
    (error(400, code="invalid_request_error"), ErrorKind.BAD_REQUEST),
    (error(401, code="invalid_api_key"), ErrorKind.BAD_REQUEST),
])
def test_status_errors_are_classified(handler, kind):
    with pytest.raises(ProviderError) as info:
        provider(handler).complete("gpt-5.6-terra", REQ, 5)
    assert info.value.kind == kind


def test_timeout_is_classified():
    def handler(request):
        raise httpx.ReadTimeout("slow", request=request)

    with pytest.raises(ProviderError) as info:
        provider(handler).complete("gpt-5.6-terra", REQ, 5)
    assert info.value.kind == ErrorKind.TIMEOUT


def test_connection_error_is_classified():
    def handler(request):
        raise httpx.ConnectError("refused", request=request)

    with pytest.raises(ProviderError) as info:
        provider(handler).complete("gpt-5.6-terra", REQ, 5)
    assert info.value.kind == ErrorKind.CONNECTION


def test_response_is_normalized_and_max_tokens_param_is_per_provider():
    seen = {}

    def handler(request):
        seen.update(__import__("json").loads(request.content))
        return httpx.Response(200, json={
            "id": "x", "object": "chat.completion", "created": 0, "model": "gpt-5.6-terra",
            "choices": [{"index": 0, "finish_reason": "tool_calls", "message": {
                "role": "assistant", "content": None,
                "tool_calls": [{"id": "c1", "type": "function",
                                "function": {"name": "get_cash", "arguments": "{}"}}]}}],
            "usage": {"prompt_tokens": 30, "completion_tokens": 7, "total_tokens": 37,
                      "prompt_tokens_details": {"cached_tokens": 10}},
        })

    out = provider(handler, max_tokens_param="max_tokens").complete("gemini-2.5-flash", REQ, 5)
    assert seen["model"] == "gemini-2.5-flash" and seen["max_tokens"] == 50
    assert "max_completion_tokens" not in seen
    assert out.tool_calls[0].name == "get_cash" and out.finish_reason == "tool_calls"
    assert (out.usage.input_tokens, out.usage.cached_input_tokens, out.usage.output_tokens) == (30, 10, 7)


def gemini(handler) -> OpenAICompatProvider:
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return OpenAICompatProvider("gemini", "g-test", base_url="https://llm.test/v1", http_client=client,
                                max_tokens_param="max_tokens")


def tool_call_reply(extra=None):
    call = {"id": "c1", "type": "function", "function": {"name": "get_cash", "arguments": "{}"}, **(extra or {})}
    return httpx.Response(200, json={
        "id": "x", "object": "chat.completion", "created": 0, "model": "m",
        "choices": [{"index": 0, "finish_reason": "tool_calls",
                     "message": {"role": "assistant", "content": None, "tool_calls": [call]}}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}})


def history(*calls):
    return {"messages": [{"role": "user", "content": "hi"}, {"role": "assistant", "content": None, "tool_calls": list(calls)},
                         {"role": "tool", "tool_call_id": "c1", "content": "{}"}]}


SIGNED = {"id": "c1", "type": "function", "function": {"name": "get_cash", "arguments": "{}"},
          "extra_content": {"google": {"thought_signature": "sig-abc"}}}
UNSIGNED = {"id": "c1", "type": "function", "function": {"name": "get_cash", "arguments": "{}"}}


def test_gemini_thought_signature_is_kept_and_sent_back():
    """Gemini 3 refuses a tool turn whose call lacks its thought signature; the adapter keeps it from the reply and
    puts it back on the assistant message for the next request."""
    from app.llm.adapter import CallInfo, ChatResult

    out = gemini(lambda r: tool_call_reply({"extra_content": {"google": {"thought_signature": "sig-abc"}}})) \
        .complete("gemini-3.8-flash", REQ, 5)
    assert out.tool_calls[0].signature == "sig-abc"
    info = CallInfo("planner", "gemini", "m", out.usage, 0, "live", "k", 0)
    msg = ChatResult(None, out.tool_calls, "tool_calls", info).assistant_message()
    assert msg["tool_calls"][0]["extra_content"] == {"google": {"thought_signature": "sig-abc"}}

    seen = {}
    gemini(lambda r: (seen.update(json.loads(r.content)), tool_call_reply())[1]).complete("m", history(SIGNED), 5)
    assert seen["messages"][1]["tool_calls"][0]["extra_content"]["google"]["thought_signature"] == "sig-abc"


def test_gemini_gets_the_placeholder_for_calls_another_provider_made():
    seen = {}
    gemini(lambda r: (seen.update(json.loads(r.content)), tool_call_reply())[1]).complete("m", history(UNSIGNED), 5)
    assert seen["messages"][1]["tool_calls"][0]["extra_content"]["google"]["thought_signature"] == \
        "skip_thought_signature_validator"


def test_openai_never_sees_gemini_fields_and_unsigned_messages_are_unchanged():
    from app.llm.adapter import CallInfo, ChatResult

    seen = {}
    provider(lambda r: (seen.update(json.loads(r.content)), tool_call_reply())[1]).complete("m", history(SIGNED), 5)
    assert "extra_content" not in seen["messages"][1]["tool_calls"][0]
    out = provider(lambda r: tool_call_reply()).complete("m", REQ, 5)
    assert out.tool_calls[0].signature is None
    info = CallInfo("planner", "openai", "m", out.usage, 0, "live", "k", 0)
    assert "extra_content" not in ChatResult(None, out.tool_calls, "tool_calls", info).assistant_message()["tool_calls"][0]
