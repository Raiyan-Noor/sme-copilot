"""The single LLM adapter. OpenAI primary, Gemini Flash fallback via its OpenAI-compatible endpoint.

This is the only module allowed to import openai (enforced by tests/unit/test_llm_imports.py). Two entry points:
- `chat(role, messages, tools=...)`: chat with optional function tools (the planner).
- `structured(role, messages, schema)`: JSON output bound to a Pydantic model, validated before it is returned.
  Never carries tools, and the extractor role cannot be given tools at all (invariant 2: the quarantined extractor
  has no tools).

Model choice comes from the profile: `dev` uses Terra everywhere; `demo` uses Sol for the planner and brief writer
and Terra for the extractor. The fallback model is the same for every role.

Fallback order for a live call:
1. OpenAI, unless it has no key or its spend has reached LLM_BUDGET_USD.
2. Gemini on insufficient_quota, 429, 5xx, timeout, connection failure or budget exhaustion. Gemini 429s are
   retried with exponential backoff. A bad request is raised as-is and never falls back.

Every call (hit, live or failed) appends to the audit log (invariant 7) with role, provider, model, tokens, cost in
micro-USD, cache status, the request key and every attempt made. Message content is never logged; the request key
points at the cached request file instead.
"""

import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Generic, Literal, TypeVar

import openai
from pydantic import BaseModel, ValidationError

import app.audit as audit_module
from app.audit import AuditLog
from app.config import Settings
from app.llm.cache import ReplayMiss, RequestCache
from app.llm.pricing import cost_microusd, price_for, usd_to_microusd
from app.llm.schema import strict_json_schema
from app.llm.spend import SpendTracker
from app.llm.types import FALLBACK_KINDS, Completion, ErrorKind, Provider, ProviderError, ToolCall, Usage

Role = Literal["planner", "extractor", "brief_writer"]
Profile = Literal["dev", "demo"]

TERRA = "gpt-5.6-terra"
SOL = "gpt-5.6-sol"
PROFILE_MODELS: dict[str, dict[str, str]] = {
    "dev": {"planner": TERRA, "extractor": TERRA, "brief_writer": TERRA},
    "demo": {"planner": SOL, "extractor": TERRA, "brief_writer": SOL},
}
GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
CACHE_NAMESPACE = "llm"

T = TypeVar("T", bound=BaseModel)


class LLMError(RuntimeError):
    pass


class LLMUnavailable(LLMError):
    """Every provider failed (or none is configured) for a live call."""

    def __init__(self, attempts: list[dict[str, Any]]):
        super().__init__(f"no LLM provider succeeded: {attempts}")
        self.attempts = attempts


class LLMOutputInvalid(LLMError):
    """A structured call returned JSON that does not validate against its schema."""


@dataclass(frozen=True)
class CallInfo:
    role: str
    provider: str
    model: str
    usage: Usage
    cost_microusd: int
    cache: Literal["hit", "miss", "off"]
    request_key: str
    audit_seq: int


@dataclass(frozen=True)
class ChatResult:
    content: str | None
    tool_calls: list[ToolCall]
    finish_reason: str | None
    info: CallInfo

    def assistant_message(self) -> dict[str, Any]:
        """This reply as an OpenAI-format assistant message, to append to the conversation."""
        msg: dict[str, Any] = {"role": "assistant", "content": self.content}
        if self.tool_calls:
            msg["tool_calls"] = [
                {"id": c.id, "type": "function", "function": {"name": c.name, "arguments": c.arguments}}
                for c in self.tool_calls
            ]
        return msg


@dataclass(frozen=True)
class StructuredResult(Generic[T]):
    data: T
    info: CallInfo


class OpenAICompatProvider:
    """An OpenAI-compatible chat-completions endpoint (OpenAI itself, or Gemini's compatibility layer).

    SDK retries are off (`max_retries=0`): the adapter decides between retrying and falling back.
    """

    def __init__(self, name: str, api_key: str, base_url: str | None = None,
                 max_tokens_param: str = "max_completion_tokens", http_client: Any = None):
        self.name = name
        self.max_tokens_param = max_tokens_param
        self._client = openai.OpenAI(api_key=api_key, base_url=base_url, max_retries=0, http_client=http_client)

    def complete(self, model: str, request: dict[str, Any], timeout_s: float) -> Completion:
        kwargs: dict[str, Any] = {"model": model, "messages": request["messages"], "timeout": timeout_s}
        if request.get("tools"):
            kwargs["tools"] = request["tools"]
            if request.get("tool_choice") is not None:
                kwargs["tool_choice"] = request["tool_choice"]
        if request.get("response_format"):
            kwargs["response_format"] = request["response_format"]
        if request.get("reasoning_effort"):
            kwargs["reasoning_effort"] = request["reasoning_effort"]
        if request.get("max_output_tokens"):
            kwargs[self.max_tokens_param] = request["max_output_tokens"]
        try:
            resp = self._client.chat.completions.create(**kwargs)
        except openai.APITimeoutError as exc:  # subclass of APIConnectionError: check first
            raise ProviderError(ErrorKind.TIMEOUT, str(exc)) from exc
        except openai.APIConnectionError as exc:
            raise ProviderError(ErrorKind.CONNECTION, str(exc)) from exc
        except openai.APIStatusError as exc:
            raise ProviderError(_classify_status(exc), str(exc), exc.status_code) from exc
        return _normalize(resp)


def _is_quota(exc: openai.APIStatusError) -> bool:
    if getattr(exc, "code", None) == "insufficient_quota":
        return True
    body = exc.body if isinstance(exc.body, dict) else {}
    err = body.get("error", body)
    return isinstance(err, dict) and "insufficient_quota" in (err.get("code"), err.get("type"))


def _classify_status(exc: openai.APIStatusError) -> ErrorKind:
    if _is_quota(exc):
        return ErrorKind.QUOTA
    if exc.status_code == 429:
        return ErrorKind.RATE_LIMIT
    if exc.status_code >= 500:
        return ErrorKind.SERVER
    if exc.status_code == 408:
        return ErrorKind.TIMEOUT
    return ErrorKind.BAD_REQUEST


def _normalize(resp: Any) -> Completion:
    choice = resp.choices[0]
    msg = choice.message
    calls = [
        ToolCall(id=c.id or f"call_{i}", name=c.function.name, arguments=c.function.arguments or "{}")
        for i, c in enumerate(msg.tool_calls or [])
    ]
    u = resp.usage
    details = getattr(u, "prompt_tokens_details", None) if u else None
    usage = Usage(
        input_tokens=(u.prompt_tokens or 0) if u else 0,
        cached_input_tokens=(getattr(details, "cached_tokens", None) or 0) if details else 0,
        output_tokens=(u.completion_tokens or 0) if u else 0,
    )
    return Completion(content=msg.content, tool_calls=calls, finish_reason=choice.finish_reason, usage=usage)


class LLMAdapter:
    def __init__(
        self,
        *,
        primary: Provider | None,
        fallback: Provider | None,
        fallback_model: str,
        cache: RequestCache,
        spend: SpendTracker,
        profile: Profile = "dev",
        budget_usd: float = 7.0,
        audit: AuditLog | None = None,
        timeout_s: float = 60.0,
        fallback_retries: int = 3,
        backoff_s: float = 1.0,
        sleep: Callable[[float], None] = time.sleep,
    ):
        if profile not in PROFILE_MODELS:
            raise ValueError(f"unknown LLM profile {profile!r}")
        self.primary = primary
        self.fallback = fallback
        self.fallback_model = fallback_model
        self.cache = cache
        self.spend = spend
        self.profile = profile
        self.budget_microusd = usd_to_microusd(budget_usd)
        self._audit = audit
        self.timeout_s = timeout_s
        self.fallback_retries = fallback_retries
        self.backoff_s = backoff_s
        self._sleep = sleep

    @classmethod
    def from_settings(cls, settings: Settings, audit: AuditLog | None = None) -> "LLMAdapter":
        """Real providers from settings. In replay mode no provider is built, so a test can never reach the network."""
        live = settings.llm_replay != "replay"
        openai_key = settings.openai_api_key.get_secret_value()
        gemini_key = settings.gemini_api_key.get_secret_value()
        primary = OpenAICompatProvider("openai", openai_key) if live and openai_key else None
        fallback = (OpenAICompatProvider("gemini", gemini_key, GEMINI_BASE_URL, max_tokens_param="max_tokens")
                    if live and gemini_key else None)
        return cls(
            primary=primary,
            fallback=fallback,
            fallback_model=settings.gemini_model,
            cache=RequestCache(settings.llm_replay_dir, settings.llm_replay),
            spend=SpendTracker(settings.data_dir / "llm_spend.json"),
            profile=settings.llm_profile,
            budget_usd=settings.llm_budget_usd,
            audit=audit,
            timeout_s=settings.llm_timeout_s,
        )

    # Public API
    def model_for(self, role: Role) -> str:
        return PROFILE_MODELS[self.profile][role]

    def budget_exhausted(self) -> bool:
        return self.spend.spent("openai") >= self.budget_microusd

    def chat(self, role: Role, messages: list[dict[str, Any]], *, tools: list[dict[str, Any]] | None = None,
             tool_choice: str | dict[str, Any] | None = None, max_output_tokens: int | None = None) -> ChatResult:
        if tools and role == "extractor":
            raise ValueError("invariant 2: the quarantined extractor has no tools")
        request: dict[str, Any] = {"messages": messages}
        if tools:
            request["tools"] = tools
            if tool_choice is not None:
                request["tool_choice"] = tool_choice
            # Chat Completions rejects function tools combined with reasoning on the GPT-5.6 models (HTTP 400:
            # "Function tools with reasoning_effort are not supported ... set reasoning_effort to 'none'").
            # Gemini's compatibility layer accepts the same value (thinking off on Flash).
            request["reasoning_effort"] = "none"
        if max_output_tokens:
            request["max_output_tokens"] = max_output_tokens
        completion, info = self._run("chat", role, request)
        return ChatResult(completion.content, list(completion.tool_calls), completion.finish_reason, info)

    def structured(self, role: Role, messages: list[dict[str, Any]], schema: type[T], *,
                   schema_name: str | None = None, max_output_tokens: int | None = None) -> StructuredResult[T]:
        """JSON output validated against `schema`. Raises LLMOutputInvalid if it does not validate."""
        name = schema_name or schema.__name__
        request: dict[str, Any] = {
            "messages": messages,
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": name, "schema": strict_json_schema(schema), "strict": True},
            },
        }
        if max_output_tokens:
            request["max_output_tokens"] = max_output_tokens
        completion, info = self._run("structured", role, request)
        try:
            data = schema.model_validate(json.loads(completion.content or ""))
        except (json.JSONDecodeError, ValidationError) as exc:
            self._log("llm.output_invalid", {"role": role, "request_key": info.request_key, "schema": name,
                                             "error": exc.__class__.__name__})
            raise LLMOutputInvalid(f"{name}: output does not match the schema") from exc
        return StructuredResult(data, info)

    # Internals
    def _log(self, kind: str, data: dict[str, Any]):
        return self._audit.append(kind, data) if self._audit else audit_module.append(kind, data)

    def _run(self, kind: str, role: Role, request: dict[str, Any]) -> tuple[Completion, CallInfo]:
        # Model-independent key content: the same request replays whichever provider or profile recorded it.
        content = {"kind": kind, "role": role, "request": request}
        attempts: list[dict[str, Any]] = []

        def live() -> dict[str, Any]:
            provider, model, completion = self._call_with_fallback(role, request, attempts)
            return {"provider": provider, "model": model, "completion": completion.model_dump()}

        began = time.perf_counter()
        try:
            outcome = self.cache.fetch(CACHE_NAMESPACE, content, live)
        except ReplayMiss as exc:
            self._log("llm.replay_miss", {"role": role, "kind": kind, "request_key": exc.key})
            raise
        except LLMError as exc:
            self._log("llm.call_failed", {"role": role, "kind": kind, "profile": self.profile,
                                          "request_key": RequestCache.key(CACHE_NAMESPACE, content),
                                          "attempts": attempts, "error": exc.__class__.__name__})
            raise

        completion = Completion.model_validate(outcome.response["completion"])
        provider, model = outcome.response["provider"], outcome.response["model"]
        cost = 0
        if outcome.status != "hit":
            cost = cost_microusd(model, completion.usage)
            self.spend.add(provider, cost)
        entry = self._log("llm.call", {
            "role": role,
            "kind": kind,
            "profile": self.profile,
            "provider": provider,
            "model": model,
            "price_known": price_for(model)[1],
            "input_tokens": completion.usage.input_tokens,
            "cached_input_tokens": completion.usage.cached_input_tokens,
            "output_tokens": completion.usage.output_tokens,
            "cost_microusd": cost,
            "openai_spent_microusd": self.spend.spent("openai"),
            "cache": outcome.status,
            "request_key": outcome.key,
            "tool_calls": [c.name for c in completion.tool_calls],
            "attempts": attempts,
            "latency_ms": round((time.perf_counter() - began) * 1000),  # wall time incl. fallbacks; ~0 on a hit
        })
        info = CallInfo(role, provider, model, completion.usage, cost, outcome.status, outcome.key, entry.seq)
        return completion, info

    def _call_with_fallback(self, role: Role, request: dict[str, Any],
                            attempts: list[dict[str, Any]]) -> tuple[str, str, Completion]:
        model = self.model_for(role)
        if self.primary is None:
            attempts.append({"provider": "openai", "model": model, "outcome": "not_configured"})
        elif self.budget_exhausted():
            attempts.append({"provider": self.primary.name, "model": model, "outcome": "budget_exhausted"})
        else:
            try:
                completion = self.primary.complete(model, request, self.timeout_s)
                attempts.append({"provider": self.primary.name, "model": model, "outcome": "ok"})
                return self.primary.name, model, completion
            except ProviderError as exc:
                attempts.append({"provider": self.primary.name, "model": model, "outcome": exc.kind.value})
                if exc.kind not in FALLBACK_KINDS:
                    raise LLMUnavailable(attempts) from exc

        if self.fallback is None:
            attempts.append({"provider": "gemini", "model": self.fallback_model, "outcome": "not_configured"})
            raise LLMUnavailable(attempts)
        for i in range(self.fallback_retries + 1):
            try:
                completion = self.fallback.complete(self.fallback_model, request, self.timeout_s)
                attempts.append({"provider": self.fallback.name, "model": self.fallback_model, "outcome": "ok"})
                return self.fallback.name, self.fallback_model, completion
            except ProviderError as exc:
                attempts.append({"provider": self.fallback.name, "model": self.fallback_model,
                                 "outcome": exc.kind.value})
                if exc.kind == ErrorKind.RATE_LIMIT and i < self.fallback_retries:
                    self._sleep(self.backoff_s * 2 ** i)
                    continue
                raise LLMUnavailable(attempts) from exc
        raise LLMUnavailable(attempts)  # unreachable; keeps type checkers honest
