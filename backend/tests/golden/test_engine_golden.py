"""Golden-file tests: every core engine fact for the seed businesses, end to end through real ingestion.

The golden file pins each fact's value, display, unit, inputs and computed_by, plus the count and SHA-256 of its
source row IDs (pinning the exact trace without storing thousands of IDs). Regenerate deliberately with
`UPDATE_GOLDEN=1 pytest tests/golden` and review the diff: a changed number is a changed claim to the owner.
"""

import hashlib
import json
import os
from pathlib import Path

import pytest

from tests.golden.pipeline import GOLDEN_DIR, BusinessInputs, compute, load_business

pytestmark = pytest.mark.golden

BUSINESSES = ("maya_corner_store", "lina_boutique")


def _record(fact) -> dict:
    ids = "\n".join(fact.source_row_ids)
    value = fact.value.isoformat() if hasattr(fact.value, "isoformat") else fact.value
    return {
        "value": value,
        "unit": fact.unit,
        "currency": fact.currency,
        "display": fact.display,
        "computed_by": fact.computed_by,
        "inputs": list(fact.inputs),
        "source_count": len(fact.source_row_ids),
        "source_sha256": hashlib.sha256(ids.encode()).hexdigest(),
    }


@pytest.fixture(scope="module")
def generated(tmp_path_factory) -> Path:
    from data.seed.generate import generate

    out = tmp_path_factory.mktemp("generated")
    generate(out)
    return out


@pytest.fixture(scope="module", params=BUSINESSES)
def business(request, generated, tmp_path_factory) -> tuple[str, BusinessInputs]:
    return request.param, load_business(generated, request.param, tmp_path_factory.mktemp("tenants"))


def test_engine_matches_golden(business):
    business_id, inputs = business
    actual = {f.id: _record(f) for f in compute(inputs)}
    path = GOLDEN_DIR / f"engine_{business_id}.json"
    if os.environ.get("UPDATE_GOLDEN") == "1":
        # One fact per line, so a changed number is a one-line diff.
        lines = [f"{json.dumps(k)}: {json.dumps(actual[k], sort_keys=True)}" for k in sorted(actual)]
        path.write_text("{\n" + ",\n".join(lines) + "\n}\n", encoding="utf-8")
    expected = json.loads(path.read_text(encoding="utf-8"))
    missing, extra = sorted(set(expected) - set(actual)), sorted(set(actual) - set(expected))
    assert not missing and not extra, f"missing {missing[:5]} extra {extra[:5]}"
    changed = [k for k in expected if expected[k] != actual[k]]
    assert not changed, f"{len(changed)} facts changed, e.g. {changed[0]}: {expected[changed[0]]} -> {actual[changed[0]]}"


def test_every_source_row_exists(business):
    _, inputs = business
    rows = {t.id for t in inputs.snapshot.transactions}
    rows |= {s.id for s in inputs.scheduled} | {s.id for s in inputs.sale_lines}
    facts = compute(inputs)
    ids = {f.id for f in facts}
    for f in facts:
        bad = [s for s in f.source_row_ids if s not in rows and not s.startswith("clock:")]
        assert not bad, (f.id, bad[:3])
        assert set(f.inputs) <= ids, (f.id, set(f.inputs) - ids)


def test_identities_hold_on_seed(business):
    _, inputs = business
    f = {x.id: x for x in compute(inputs)}
    months = sorted({k.split(".")[1] for k in f if k.startswith("pnl.") and k.endswith(".revenue")
                     and k.count(".") == 2})
    assert len(months) >= 6
    for m in months:
        p = f"pnl.{m}"
        assert f[f"{p}.gross_profit"].value == f[f"{p}.revenue"].value - f[f"{p}.cogs"].value
        assert f[f"{p}.operating_profit"].value == f[f"{p}.gross_profit"].value - f[f"{p}.operating_expenses"].value
    cash = f["cash.balance"].value
    assert cash == sum(v.value for k, v in f.items() if k.startswith("cash.balance."))
    for n in (30, 60, 90):
        lo, mid, hi = (f[f"forecast.{n}d.end_balance{s}"].value for s in ("_low", "", "_high"))
        assert lo <= mid <= hi
        assert f[f"forecast.{n}d.end_balance"].value == \
            cash + f[f"forecast.{n}d.inflows"].value - f[f"forecast.{n}d.outflows"].value
