"""explain_fact: walk a Fact back to the Facts it was computed from and the rows it cites (invariant 4).

Pure: the caller passes the request's FactStore and a resolver that looks up a source ID (ledger transaction,
scheduled item, sale line) in the business's data. Two kinds of reference are not rows and are never looked up:
`clock:<...>` (the simulated clock) and `pack:<id>@<version>#<path>` (Skill Pack config, shown as "from the Skill
Pack").

Invariant 2: a row's `text` is untrusted statement content. It is filled only when `include_text=True`, which the
owner-facing API uses. The planner's explain_fact tool must call with `include_text=False`, so it receives IDs,
dates, amounts and categories only.
"""

import datetime as dt
from collections import deque
from collections.abc import Callable
from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.firewall.fact import Fact
from app.firewall.store import FactStore

SourceKind = Literal["transaction", "scheduled_item", "sale_line", "clock", "pack", "unknown"]


class SourceRow(BaseModel):
    """One cited source. Money is integer minor units; `text` is untrusted and owner-UI only."""

    model_config = ConfigDict(frozen=True)

    id: str
    kind: SourceKind
    date: dt.date | None = None
    amount_minor: int | None = None
    currency: str | None = None
    category: str | None = None
    account_id: str | None = None
    text: str | None = None


class FactTrace(BaseModel):
    """The fact, every fact it was computed from (breadth first, each once), and the rows they cite.

    `rows` is capped at the requested limit, the explained fact's own rows first; `rows_total` counts them all.
    `missing_inputs` lists input IDs not computed in this request (should be empty; non-empty means a bug).
    """

    fact_id: str
    facts: list[Fact]
    rows: list[SourceRow]
    rows_total: int
    missing_inputs: list[str]


Resolver = Callable[[str], SourceRow | None]


def _source(ref: str, resolve: Resolver, include_text: bool) -> SourceRow:
    if ref.startswith("clock:"):
        return SourceRow(id=ref, kind="clock", text="simulated clock" if include_text else None)
    if ref.startswith("pack:"):
        return SourceRow(id=ref, kind="pack", text="from the Skill Pack" if include_text else None)
    row = resolve(ref)
    if row is None:
        return SourceRow(id=ref, kind="unknown")
    return row if include_text else row.model_copy(update={"text": None})


def explain(fact_id: str, store: FactStore, resolve: Resolver, *, max_rows: int = 50,
            include_text: bool = False) -> FactTrace:
    """Trace `fact_id` (raises UnknownFactError if it was not computed in this request)."""
    root = store.get(fact_id)
    facts: list[Fact] = []
    missing: list[str] = []
    seen = {root.id}
    queue = deque([root])
    while queue:
        fact = queue.popleft()
        facts.append(fact)
        for input_id in fact.inputs:
            if input_id in seen:
                continue
            seen.add(input_id)
            if input_id in store:
                queue.append(store.get(input_id))
            else:
                missing.append(input_id)

    refs: list[str] = []
    cited: set[str] = set()
    for fact in facts:
        for ref in fact.source_row_ids:
            if ref not in cited:
                cited.add(ref)
                refs.append(ref)
    rows = [_source(ref, resolve, include_text) for ref in refs[:max_rows]]
    return FactTrace(fact_id=root.id, facts=facts, rows=rows, rows_total=len(refs), missing_inputs=missing)
