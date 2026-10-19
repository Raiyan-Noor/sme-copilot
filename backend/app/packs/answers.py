"""Owner answers to a pack's advisor questions, turned into what the engine uses.

Each question in the pack declares one effect (packs/schema.py AnswerEffect):
- `fact`: the answer becomes an owner-stated Fact `owner.<fact>` citing `owner:<question id>` (invariant 4: the
  owner sees where it came from in the trace).
- `detector` + `param`: the answer replaces that detector's param for this business only, e.g. "flag returns above
  the rate you told me is normal". The pack file itself never changes.

"Not sure" (value None) leaves the pack default. Answers to questions the pack no longer has are ignored.
"""

from app.firewall.fact import Fact
from app.packs.schema import Pack

BY = "packs.answers.effective_pack"


def _display(value: float, unit: str) -> str:
    if unit == "ratio":
        return f"{value * 100:.1f}%"
    if unit == "days":
        return "1 day" if value == 1 else f"{value:g} days"
    return f"{value:g}"


def effective_pack(pack: Pack, answers: dict[str, float | None]) -> tuple[Pack, list[Fact]]:
    """(pack with this business's detector params, owner-stated facts)."""
    facts: list[Fact] = []
    overrides: dict[str, dict[str, float]] = {}
    for q in pack.advisor_questions:
        value = answers.get(q.id)
        if value is None:
            continue
        e = q.effect
        if e.fact is not None:
            v = int(value) if e.unit == "count" else float(value)
            facts.append(Fact(id=f"owner.{e.fact}", value=v, unit=e.unit, display=_display(value, e.unit),
                              source_row_ids=(f"owner:{q.id}",), computed_by=BY))
        else:
            overrides.setdefault(e.detector, {})[e.param] = int(value) if float(value).is_integer() else value
    if not overrides:
        return pack, facts
    doc = pack.model_dump(mode="json")
    for d in doc["leak_detectors"]:
        d["params"] = {**d["params"], **overrides.get(d["detector"], {})}
    return Pack.model_validate(doc), facts
