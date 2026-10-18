"""Generic record/replay request cache (LLM_REPLAY=record|replay|off). Used by the LLM adapter (namespace "llm")
and, later, by anchoring to mock the testnet RPC (namespace "rpc"), so CI never touches the network.

A request is keyed by the SHA-256 of `{namespace, content}` serialized as sorted-key JSON. Callers put only
provider- and model-independent content in `content`, so a response recorded on one provider or profile replays on
another. Each entry is one JSON file, `<root>/<namespace>/<key>.json`, holding the request and the response, so a
reviewer can read what was recorded and diffs stay small.

Modes:
- `replay`: a hit returns the stored response; a miss raises `ReplayMiss`. The live call is never made.
- `record`: a hit returns the stored response (no spend); a miss makes the call and stores the result.
- `off`: always makes the call and stores nothing.
"""

import hashlib
import json
import os
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

Mode = Literal["record", "replay", "off"]
_NAMESPACE = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")


class ReplayMiss(LookupError):
    """Replay mode and no recorded response for this request."""

    def __init__(self, namespace: str, key: str):
        super().__init__(f"no recorded {namespace} response for key {key}; record it with LLM_REPLAY=record")
        self.namespace = namespace
        self.key = key


@dataclass(frozen=True)
class CacheOutcome:
    response: dict[str, Any]
    key: str
    status: Literal["hit", "miss", "off"]


def _dumps(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


class RequestCache:
    def __init__(self, root: Path, mode: Mode):
        if mode not in ("record", "replay", "off"):
            raise ValueError(f"unknown replay mode {mode!r}")
        self.root = Path(root)
        self.mode: Mode = mode

    @staticmethod
    def key(namespace: str, content: Any) -> str:
        if not _NAMESPACE.match(namespace):
            raise ValueError(f"bad cache namespace {namespace!r}")
        return hashlib.sha256(_dumps({"namespace": namespace, "content": content}).encode()).hexdigest()

    def _path(self, namespace: str, key: str) -> Path:
        return self.root / namespace / f"{key}.json"

    def get(self, namespace: str, key: str) -> dict[str, Any] | None:
        """The stored response, or None. Always None in `off` mode."""
        if self.mode == "off":
            return None
        path = self._path(namespace, key)
        if not path.is_file():
            return None
        return json.loads(path.read_text(encoding="utf-8"))["response"]

    def put(self, namespace: str, key: str, content: Any, response: dict[str, Any]) -> None:
        """Store a response (record mode only; a no-op otherwise). Written atomically."""
        if self.mode != "record":
            return
        path = self._path(namespace, key)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(f".{os.getpid()}.tmp")
        entry = {"namespace": namespace, "key": key, "request": content, "response": response}
        tmp.write_text(json.dumps(entry, sort_keys=True, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        tmp.replace(path)

    def fetch(self, namespace: str, content: Any, call: Callable[[], dict[str, Any]]) -> CacheOutcome:
        """Return the cached response for `content`, or (record/off) run `call` and maybe store its result."""
        key = self.key(namespace, content)
        stored = self.get(namespace, key)
        if stored is not None:
            return CacheOutcome(stored, key, "hit")
        if self.mode == "replay":
            raise ReplayMiss(namespace, key)
        response = call()
        self.put(namespace, key, content, response)
        return CacheOutcome(response, key, "off" if self.mode == "off" else "miss")
