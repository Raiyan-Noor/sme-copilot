"""Hash-chained JSONL audit log: append, verify, export (invariant 7).

Every tool call, fact computation, LLM call, gateway decision and execution is appended here. Nothing writes to
the log except `append()` (module level, on the configured default log) or `AuditLog.append()` on an injected log.
"""

from typing import Any

from app.audit.canonical import canonical_hash, canonical_json, sha256_hex
from app.audit.log import GENESIS_HASH, AuditEntry, AuditLog, Head, VerifyResult

__all__ = [
    "GENESIS_HASH",
    "AuditEntry",
    "AuditLog",
    "Head",
    "VerifyResult",
    "append",
    "canonical_hash",
    "canonical_json",
    "configure",
    "get_log",
    "head",
    "sha256_hex",
]

_default: AuditLog | None = None


def configure(log: AuditLog) -> None:
    """Set the process-wide default log (done once at app startup)."""
    global _default
    _default = log


def get_log() -> AuditLog:
    if _default is None:
        raise RuntimeError("audit log not configured; call app.audit.configure() at startup")
    return _default


def append(kind: str, data: dict[str, Any] | None = None) -> AuditEntry:
    return get_log().append(kind, data)


def head() -> Head:
    return get_log().head()
