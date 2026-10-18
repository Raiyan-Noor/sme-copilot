"""Placeholder renderer (invariant 4).

Turns checked LLM output into what the owner sees: each `{fact:<id>}` becomes that Fact's `display`. Rendering
refuses any text that fails the digit check, so there is no path from LLM output to the screen that skips it.
The result also carries segments, so the UI can make each number clickable for its source-row trace.
"""

from dataclasses import dataclass

from app.firewall.digit_check import PLACEHOLDER_RE, CheckResult, check_output
from app.firewall.store import FactStore


class FirewallViolation(ValueError):
    """LLM output broke the Numeric Firewall; `result` lists every violation."""

    def __init__(self, result: CheckResult) -> None:
        self.result = result
        kinds = ", ".join(sorted({v.kind.value for v in result.violations}))
        super().__init__(f"{len(result.violations)} numeric firewall violation(s): {kinds}")


@dataclass(frozen=True, slots=True)
class Segment:
    text: str
    fact_id: str | None = None  # set when this segment is a rendered fact


@dataclass(frozen=True, slots=True)
class Rendered:
    text: str
    segments: tuple[Segment, ...]
    fact_ids: tuple[str, ...]


def render(text: str, store: FactStore) -> Rendered:
    """Check `text` and substitute every placeholder with its fact's display string.

    Raises FirewallViolation if any digit sits outside a placeholder, a placeholder is malformed, or it cites a
    fact not in this request's store.
    """
    result = check_output(text, store)
    if not result.ok:
        raise FirewallViolation(result)
    segments: list[Segment] = []
    cursor = 0
    for m in PLACEHOLDER_RE.finditer(text):
        if m.start() > cursor:
            segments.append(Segment(text[cursor : m.start()]))
        fact = store.get(m.group(1))
        segments.append(Segment(fact.display, fact.id))
        cursor = m.end()
    if cursor < len(text):
        segments.append(Segment(text[cursor:]))
    return Rendered("".join(s.text for s in segments), tuple(segments), result.fact_ids)
