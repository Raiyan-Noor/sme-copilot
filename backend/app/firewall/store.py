"""Per-request fact store (invariant 4).

Create one FactStore per request (or per planner turn) and register every Fact a tool returns. The renderer only
resolves IDs present in this store, so the LLM can cite only facts that were actually computed for this request,
never a remembered or invented ID. There is deliberately no module-level store.
"""

from collections.abc import Callable, Iterable, Iterator

from app.firewall.fact import Fact


class FactConflictError(ValueError):
    """A different Fact was registered under an ID already in the store."""


class UnknownFactError(KeyError):
    """The requested fact ID was not computed in this request."""


class FactStore:
    """Holds the Facts computed for one request, keyed by ID.

    Re-adding an identical Fact is a no-op; adding a different Fact under the same ID raises, so a value cannot be
    silently swapped after the planner has seen its ID. `on_add` is called once per newly stored Fact, which is
    where the audit log hooks in (invariant 7).
    """

    def __init__(self, on_add: Callable[[Fact], None] | None = None) -> None:
        self._facts: dict[str, Fact] = {}
        self._on_add = on_add

    def add(self, fact: Fact) -> Fact:
        existing = self._facts.get(fact.id)
        if existing is not None:
            if existing != fact:
                raise FactConflictError(f"fact {fact.id!r} already holds a different value")
            return existing
        self._facts[fact.id] = fact
        if self._on_add is not None:
            self._on_add(fact)
        return fact

    def add_all(self, facts: Iterable[Fact]) -> list[Fact]:
        return [self.add(f) for f in facts]

    def get(self, fact_id: str) -> Fact:
        try:
            return self._facts[fact_id]
        except KeyError:
            raise UnknownFactError(fact_id) from None

    def __contains__(self, fact_id: object) -> bool:
        return fact_id in self._facts

    def __iter__(self) -> Iterator[Fact]:
        return iter(self._facts.values())

    def __len__(self) -> int:
        return len(self._facts)

    def ids(self) -> frozenset[str]:
        return frozenset(self._facts)
