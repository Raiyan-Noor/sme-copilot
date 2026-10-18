"""Digit check on LLM output (invariant 4).

Text passes only if every number-like character sits inside a well-formed `{fact:<id>}` placeholder. "Number-like"
is broader than ASCII [0-9]: any Unicode numeric character (Arabic-Indic, fullwidth, mathematical, superscripts,
fractions, circled and Roman numerals, CJK numerals) and any character whose NFKC form contains one (e.g. U+33E9,
the telegraph symbol for "day 10"). The check runs on the raw text; placeholders are matched in strict ASCII, so a
fullwidth or lookalike placeholder is not a placeholder and its digits are violations.

What this cannot catch: numbers spelled as words ("twelve", "first"). The planner prompt forbids them unless a
fact backs them; the check guarantees no digit the LLM produced ever reaches the owner.
"""

import re
import unicodedata
from collections.abc import Container
from dataclasses import dataclass
from enum import StrEnum

# A cited ID must start with a letter: if `{fact:1500}` were a placeholder, a number could pass the check whenever
# no store is consulted. The rest of the alphabet matches Fact.id.
PLACEHOLDER_ID_PATTERN = r"[a-z][a-z0-9_.:\-]{0,127}"
PLACEHOLDER_RE = re.compile(rf"\{{fact:({PLACEHOLDER_ID_PATTERN})\}}", re.ASCII)
# Anything that looks like an attempt at a placeholder but is not well formed: `{fact: x}`, `{FACT:x}`,
# `{fact:1500}`, an unclosed `{fact:x`. Checked on the NFKC form so fullwidth braces count too.
_PLACEHOLDER_ATTEMPT_RE = re.compile(r"\{\s*fact\s*:", re.IGNORECASE)


class ViolationKind(StrEnum):
    DIGIT = "digit"
    MALFORMED_PLACEHOLDER = "malformed_placeholder"
    UNKNOWN_FACT = "unknown_fact"


@dataclass(frozen=True, slots=True)
class Violation:
    kind: ViolationKind
    start: int  # index into the checked text
    end: int
    snippet: str


@dataclass(frozen=True, slots=True)
class CheckResult:
    violations: tuple[Violation, ...]
    fact_ids: tuple[str, ...]  # placeholders found, in order of appearance

    @property
    def ok(self) -> bool:
        return not self.violations


def is_numeric_char(ch: str) -> bool:
    """True for any character that is, or normalizes to, a numeric character."""
    if ch.isnumeric():
        return True
    normalized = unicodedata.normalize("NFKC", ch)
    return normalized != ch and any(c.isnumeric() for c in normalized)


def _numeric_runs(text: str, offset: int) -> list[Violation]:
    runs: list[Violation] = []
    i = 0
    while i < len(text):
        if is_numeric_char(text[i]):
            j = i + 1
            while j < len(text) and is_numeric_char(text[j]):
                j += 1
            runs.append(Violation(ViolationKind.DIGIT, offset + i, offset + j, text[i:j]))
            i = j
        else:
            i += 1
    return runs


def _malformed_attempts(text: str, offset: int) -> list[Violation]:
    # NFKC can change string length, so map back by checking each start position in the original text.
    found: list[Violation] = []
    for i in range(len(text)):
        if text[i] in "{\uff5b\ufe5b" and _PLACEHOLDER_ATTEMPT_RE.match(unicodedata.normalize("NFKC", text[i : i + 16])):
            found.append(Violation(ViolationKind.MALFORMED_PLACEHOLDER, offset + i, offset + i + 1, text[i : i + 16]))
    return found


def check_output(text: str, known_fact_ids: Container[str] | None = None) -> CheckResult:
    """Check LLM output against the Numeric Firewall.

    Flags every numeric run outside a valid placeholder, every malformed placeholder attempt, and, when
    `known_fact_ids` is given (normally a FactStore), every placeholder whose ID was not computed in this request.
    """
    violations: list[Violation] = []
    fact_ids: list[str] = []
    cursor = 0
    for m in PLACEHOLDER_RE.finditer(text):
        gap = text[cursor : m.start()]
        violations += _numeric_runs(gap, cursor) + _malformed_attempts(gap, cursor)
        fact_id = m.group(1)
        fact_ids.append(fact_id)
        if known_fact_ids is not None and fact_id not in known_fact_ids:
            violations.append(Violation(ViolationKind.UNKNOWN_FACT, m.start(), m.end(), m.group(0)))
        cursor = m.end()
    tail = text[cursor:]
    violations += _numeric_runs(tail, cursor) + _malformed_attempts(tail, cursor)
    violations.sort(key=lambda v: v.start)
    return CheckResult(tuple(violations), tuple(fact_ids))
