"""Canonical JSON and SHA-256 (CLAUDE.md, Conventions; invariants 7 and 9).

Anything that is hashed (audit entries, signed mandates, exported Passports) is serialized here: sorted keys, no
insignificant whitespace, UTF-8, non-ASCII kept as-is. A verifier, including the browser, can recompute the exact
bytes and hash from the file. Floats are refused: money is integer minor units, and float formatting differs
between Python and JavaScript, so a float would make a signature or anchor unverifiable.
"""

import hashlib
import json
from typing import Any


class CanonicalError(ValueError):
    """A value cannot be serialized canonically."""


def _check(value: Any) -> None:
    if isinstance(value, float):
        raise CanonicalError("floats are not allowed in canonical JSON; use integer minor units or a string")
    if isinstance(value, dict):
        for k, v in value.items():
            if not isinstance(k, str):
                raise CanonicalError(f"canonical JSON keys must be strings, got {type(k).__name__}")
            _check(v)
    elif isinstance(value, (list, tuple)):
        for v in value:
            _check(v)


def canonical_json(value: Any) -> bytes:
    """Serialize `value` to canonical JSON bytes."""
    _check(value)
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_hash(value: Any) -> str:
    """SHA-256 hex of the canonical JSON of `value`."""
    return sha256_hex(canonical_json(value))
