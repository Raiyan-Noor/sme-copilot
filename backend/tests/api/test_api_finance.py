"""Facts, explain_fact, P&L, cash, forecast and KPIs over HTTP.

The API serves the same numbers as the engine golden files (same seed, same ingestion path), every fact traces to
rows that exist, and a computation is logged once per ledger version and simulated day.
"""

import json
import re

import pytest

from app.firewall.explain import explain
from app.services.finance import resolver
from tests.api.conftest import LINA, MAYA
from tests.golden.pipeline import GOLDEN_DIR

TOKEN_IN_ID = re.compile(r"\.(acct|tel|nid)_[a-z]{12}")


@pytest.mark.parametrize("business_id", [MAYA, LINA])
def test_api_facts_match_engine_golden(read_api, business_id):
    golden = json.loads((GOLDEN_DIR / f"engine_{business_id.replace('-', '_')}.json").read_text(encoding="utf-8"))
    served = {f["id"]: f for f in read_api.get(f"/businesses/{business_id}/facts", params={"limit": 2000}).json()[
        "facts"]}
    # Account fact IDs embed the tenant's PII token, which differs per tenant key; every other ID must match.
    comparable = [k for k in golden if not TOKEN_IN_ID.search(k)]
    assert len(comparable) > 400
    for fid in comparable:
        assert fid in served, fid
        g, s = golden[fid], served[fid]
        assert (s["value"], s["display"], s["unit"], len(s["source_row_ids"])) == (
            g["value"], g["display"], g["unit"], g["source_count"]), fid


def test_facts_prefix_filter(read_api):
    body = read_api.get(f"/businesses/{MAYA}/facts", params={"prefix": "forecast.30d."}).json()
    assert body["total"] == 10 and all(f["id"].startswith("forecast.30d.") for f in body["facts"])
    assert body["pack_ref"] == "pack:grocery_retail@1"


def test_every_fact_traces_to_known_rows_and_facts(read_api):
    rt = read_api.app.state.runtime
    for business_id in (MAYA, LINA):
        c = rt.facts(business_id)
        resolve = resolver(c.inputs)
        for fact in c.store:
            assert all(i in c.store for i in fact.inputs), fact.id
            for ref in fact.source_row_ids:
                assert ref.startswith(("clock:", "pack:")) or resolve(ref) is not None, (fact.id, ref)


def test_explain_walks_inputs_to_rows(read_api):
    r = read_api.get(f"/businesses/{MAYA}/facts/runway.days/explain", params={"max_rows": 5})
    assert r.status_code == 200
    trace = r.json()
    ids = [f["id"] for f in trace["facts"]]
    assert ids[0] == "runway.days" and "cash.balance" in ids
    assert trace["missing_inputs"] == []
    assert len(trace["rows"]) <= 5 and trace["rows_total"] >= len(trace["rows"])

    balance = read_api.get(f"/businesses/{MAYA}/facts/cash.balance/explain").json()
    assert {r["kind"] for r in balance["rows"]} == {"transaction"}
    assert all(r["text"] for r in balance["rows"])  # owner view carries the statement text


def test_explain_for_the_planner_drops_untrusted_text(read_api):
    c = read_api.app.state.runtime.facts(MAYA)
    trace = explain("cash.balance", c.store, resolver(c.inputs), include_text=False)
    assert trace.rows and all(r.text is None for r in trace.rows)


def test_explain_benchmark_bound_cites_the_pack(read_api):
    trace = read_api.get(f"/businesses/{MAYA}/facts/benchmark.gross_margin.min/explain").json()
    assert [r["kind"] for r in trace["rows"]] == ["pack"]
    assert trace["rows"][0]["id"].startswith("pack:grocery_retail@1#")


def test_explain_unknown_fact_is_404(read_api):
    r = read_api.get(f"/businesses/{MAYA}/facts/cash.nope/explain")
    assert r.status_code == 404 and r.json()["detail"] == "unknown fact: cash.nope"


def test_pnl_by_month_and_week(read_api):
    month = read_api.get(f"/businesses/{MAYA}/pnl").json()
    keys = [p["period"] for p in month["periods"]]
    assert keys == sorted(keys) and keys[0] == "2026-04" and keys[-1] == "2026-10"
    sept = next(p for p in month["periods"] if p["period"] == "2026-09")
    assert sept["lines"]["revenue"]["id"] == "pnl.2026-09.revenue"
    assert sept["lines"]["revenue"]["unit"] == "money" and sept["lines"]["revenue"]["value"] > 0
    assert sept["lines"]["gross_margin"]["unit"] == "ratio"
    assert sept["days_covered"]["value"] == 30

    week = read_api.get(f"/businesses/{MAYA}/pnl", params={"period": "week"}).json()
    assert len(week["periods"]) >= 25 and all(re.fullmatch(r"\d{4}-w\d{2}", p["period"]) for p in week["periods"])
    assert read_api.get(f"/businesses/{MAYA}/pnl", params={"period": "year"}).status_code == 422


def test_cash_position(read_api):
    cash = read_api.get(f"/businesses/{MAYA}/cash").json()
    assert cash["as_of"] == "2026-10-19"
    assert cash["balance"]["value"] == sum(a["value"] for a in cash["accounts"])
    assert len(cash["accounts"]) == 3
    assert cash["buffer_days"]["unit"] == "days"
    assert cash["runway_days"]["id"] == "runway.days"


def test_forecast_horizons_and_daily_path(read_api):
    fc = read_api.get(f"/businesses/{MAYA}/forecast").json()
    assert [h["days"] for h in fc["horizons"]] == [30, 60, 90]
    assert len(fc["daily"]) == 90 and fc["daily"][0]["date"] == "2026-10-19"
    for day in fc["daily"]:
        assert day["low"]["value"] <= day["expected"]["value"] <= day["high"]["value"]
    h30 = fc["horizons"][0]
    assert h30["end_balance"]["value"] == fc["daily"][29]["expected"]["value"]


def test_kpis_against_synthetic_benchmarks(read_api):
    body = read_api.get(f"/businesses/{MAYA}/kpis").json()
    assert body["benchmarks_synthetic"] is True
    rows = {k["kpi_id"]: k for k in body["kpis"]}
    assert rows["buffer_days"]["value"]["id"] == "cash.buffer_days"
    fee = rows["payment_fee_share"]
    assert fee["status"] == "above" and fee["healthy_max"]["id"] == "benchmark.payment_fee_share.max"


def test_facts_are_computed_and_logged_once_per_day(api):
    for _ in range(3):
        api.get(f"/businesses/{MAYA}/cash")
        api.get(f"/businesses/{MAYA}/forecast")
    logged = api.get("/audit", params={"kind": "engine.facts_computed"}).json()["entries"]
    assert len(logged) == 1
    assert logged[0]["data"]["business_id"] == MAYA and logged[0]["data"]["facts"] > 1000

    api.post("/clock/advance", json={"days": 1})
    cash = api.get(f"/businesses/{MAYA}/cash").json()
    assert cash["as_of"] == "2026-10-20"
    assert api.get("/audit", params={"kind": "engine.facts_computed"}).json()["total"] == 2


def test_explain_is_logged(api):
    api.get(f"/businesses/{MAYA}/facts/cash.balance/explain")
    entry = api.get("/audit", params={"kind": "tool.explain_fact"}).json()["entries"][0]
    assert entry["data"]["fact_id"] == "cash.balance" and entry["data"]["caller"] == "api"
