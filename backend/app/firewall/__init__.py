"""Numeric Firewall (invariant 4): the Fact model, the fact store, the {fact:<id>} placeholder renderer and the
digit check that rejects any [0-9] in LLM output outside a placeholder.
"""

from app.firewall.digit_check import CheckResult, Violation, ViolationKind, check_output, is_numeric_char
from app.firewall.fact import Fact
from app.firewall.render import FirewallViolation, Rendered, Segment, render
from app.firewall.store import FactConflictError, FactStore, UnknownFactError

__all__ = [
    "CheckResult",
    "Fact",
    "FactConflictError",
    "FactStore",
    "FirewallViolation",
    "Rendered",
    "Segment",
    "UnknownFactError",
    "Violation",
    "ViolationKind",
    "check_output",
    "is_numeric_char",
    "render",
]
