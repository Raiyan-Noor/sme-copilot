"""Provider-neutral request/response types for the LLM adapter. Imports no SDK, so fakes and callers can use them.

Providers raise `ProviderError` with a normalized `ErrorKind`; the adapter falls back to the next provider only for
the kinds in `FALLBACK_KINDS` (insufficient_quota, 429, 5xx, timeout, connection failure). A bad request is a bug in
our request and would fail on any provider, so it is raised, not masked by a fallback.
"""

import json
from enum import StrEnum
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict


class Usage(BaseModel):
    model_config = ConfigDict(frozen=True)

    input_tokens: int = 0
    cached_input_tokens: int = 0
    output_tokens: int = 0


class ToolCall(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    name: str
    arguments: str  # JSON text exactly as the model produced it; parse and validate before use

    def args(self) -> Any:
        return json.loads(self.arguments)


class Completion(BaseModel):
    """What a provider returned, normalized. This is what the record/replay cache stores."""

    model_config = ConfigDict(frozen=True)

    content: str | None = None
    tool_calls: list[ToolCall] = []
    finish_reason: str | None = None
    usage: Usage = Usage()


class ErrorKind(StrEnum):
    QUOTA = "insufficient_quota"
    RATE_LIMIT = "rate_limited"
    SERVER = "server_error"
    TIMEOUT = "timeout"
    CONNECTION = "connection_error"
    BAD_REQUEST = "bad_request"


FALLBACK_KINDS = frozenset({ErrorKind.QUOTA, ErrorKind.RATE_LIMIT, ErrorKind.SERVER, ErrorKind.TIMEOUT,
                            ErrorKind.CONNECTION})


class ProviderError(Exception):
    def __init__(self, kind: ErrorKind, message: str = "", status: int | None = None):
        super().__init__(message or kind.value)
        self.kind = kind
        self.status = status


class Provider(Protocol):
    """One OpenAI-compatible chat endpoint. `request` is model-free: messages, tools, tool_choice,
    response_format, max_output_tokens."""

    name: str

    def complete(self, model: str, request: dict[str, Any], timeout_s: float) -> Completion: ...
