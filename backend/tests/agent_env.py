"""Agent test helpers: deterministic seeded tenants and a scripted stand-in for the LLM adapter.

Record/replay keys hash the whole planner request, including tool results. Tool results carry IDs that derive from
the tenant's PII key (account tokens, transaction IDs behind leak fact IDs), which is random per tenant, so the
agent suites build their tenants with a fixed key. Same seed + same key = same requests = replay hits.
"""

import functools
import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.ledger import schema
from app.llm.types import ToolCall
from app.main import PASSCODE_HEADER, create_app
from app.services import businesses
from app.services.runtime import Runtime
from tests.helpers import TEST_PASSCODE, make_settings

MAYA = "maya-corner-store"
FIXED_PII_KEY = bytes(range(32))


def build_template(root: Path) -> tuple[Path, Path]:
    """Generate the seed and load it into tenants keyed with FIXED_PII_KEY. Returns (data_dir, seed_dir)."""
    from data.seed.generate import generate

    seed_dir, data_dir = root / "generated", root / "tenants"
    generate(seed_dir)
    fixed = functools.partial(schema.create_tenant, pii_key=FIXED_PII_KEY)
    with patch.object(businesses, "create_tenant", fixed):
        Runtime(make_settings(data_dir=data_dir, seed_dir=seed_dir)).ensure_ready()
    return data_dir, seed_dir


def copy_data_dir(template: Path, dest: Path) -> Path:
    shutil.copytree(template, dest)
    return dest


def agent_client(data_dir: Path, seed_dir: Path, llm: Any = None, **overrides) -> TestClient:
    """An app over copied tenants. `llm` replaces the runtime's adapter (a FakeLLM); None keeps the real one."""
    app = create_app(make_settings(data_dir=data_dir, seed_dir=seed_dir, **overrides))
    if llm is not None:
        app.state.runtime._llm = llm
    return TestClient(app, headers={PASSCODE_HEADER: TEST_PASSCODE})


@dataclass
class FakeResult:
    content: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    finish_reason: str | None = "stop"

    def assistant_message(self) -> dict[str, Any]:
        msg: dict[str, Any] = {"role": "assistant", "content": self.content}
        if self.tool_calls:
            msg["tool_calls"] = [{"id": c.id, "type": "function",
                                  "function": {"name": c.name, "arguments": c.arguments}} for c in self.tool_calls]
        return msg


def text(content: str) -> FakeResult:
    return FakeResult(content=content)


def calls(*specs: tuple[str, dict]) -> FakeResult:
    """One assistant step calling tools: calls(("get_cash_position", {}), ...)."""
    return FakeResult(tool_calls=[ToolCall(id=f"call_{name}_{i}", name=name, arguments=json.dumps(args))
                                  for i, (name, args) in enumerate(specs)])


class FakeLLM:
    """Plays back scripted steps in order and records every request the planner made."""

    def __init__(self, *steps: FakeResult | Exception):
        self.steps = list(steps)
        self.requests: list[list[dict[str, Any]]] = []

    def chat(self, role, messages, *, tools=None, tool_choice=None, max_output_tokens=None):
        assert role == "planner" and tools, "the planner always calls with its tools"
        self.requests.append([dict(m) for m in messages])
        step = self.steps.pop(0)
        if isinstance(step, Exception):
            raise step
        return step
