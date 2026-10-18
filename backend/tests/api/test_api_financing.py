"""Financing and Readiness Passport routes: match, Passport, canonical export, and the T3 application flow."""

from app.audit.canonical import canonical_json, sha256_hex
from tests.api.conftest import MAYA


def test_financing_lists_every_product_with_rule_results_and_facts(read_api):
    body = read_api.get(f"/businesses/{MAYA}/financing").json()
    products = {p["product_id"]: p for p in body["match"]["products"]}
    assert 6 <= len(products) <= 10 and body["match"]["synthetic"] is True
    nano = products["prd_nano"]
    assert nano["status"] == "eligible" and nano["capped_by"] == "repayment_safety"
    assert nano["safe_amount_fact_id"] in body["facts"]
    digital = products["prd_digital_line"]
    assert any(r["rule"] == "min_digital_history_months" and not r["passed"] for r in digital["rules"])
    for p in products.values():
        for r in p["rules"]:
            assert r["metric_fact_id"] in body["facts"] and r["threshold_fact_id"] in body["facts"]


def test_passport_has_band_factors_and_path(read_api):
    body = read_api.get(f"/businesses/{MAYA}/passport").json()
    pp = body["passport"]
    assert pp["band_label"] and len(pp["factors"]) == 5 and pp["path_to_eligibility"]
    assert all(f["raw_fact_id"] in body["facts"] for f in pp["factors"])


def test_passport_export_round_trip(api):
    exported = api.post(f"/businesses/{MAYA}/passport/export").json()
    sha = exported["sha256"]
    assert sha == sha256_hex(canonical_json(exported["document"]))
    assert [e["sha256"] for e in api.get(f"/businesses/{MAYA}/passport/exports").json()] == [sha]
    assert api.get(f"/businesses/{MAYA}/passport/exports/{sha}").json()["document"] == exported["document"]
    logged = api.get("/audit", params={"kind": "passport.exported"}).json()["entries"]
    assert logged[-1]["data"]["sha256"] == sha
    assert api.get(f"/businesses/{MAYA}/passport/exports/{'0' * 64}").status_code == 404


def test_application_is_drafted_at_the_safe_amount_and_waits_for_signature(api):
    r = api.post(f"/businesses/{MAYA}/financing/applications", json={"product_id": "prd_nano"})
    assert r.status_code == 200, r.text
    body = r.json()
    decision = body["decision"]
    assert decision["status"] == "pending_approval" and decision["effective_tier"] == "T3"
    assert decision["approval"]["args"] == {"product_id": "prd_nano", "amount_minor": body["draft"]["amount_minor"],
                                            "draft_id": body["draft_id"]}
    safe = api.get(f"/businesses/{MAYA}/financing").json()["facts"]["financing.prd_nano.safe_amount"]["value"]
    assert body["draft"]["amount_minor"] == safe
    view = api.get(f"/businesses/{MAYA}/financing/applications/{body['draft_id']}").json()
    assert view["draft"] == body["draft"] and view["sha256"] == body["draft_sha256"]
    assert body["draft"]["readiness"]["passport_sha256"] == body["passport_sha256"]
    kinds = [e["kind"] for e in api.get("/audit").json()["entries"]]
    assert "financing.draft_prepared" in kinds and "gateway.decision" in kinds


def test_application_over_the_safe_amount_or_for_an_ineligible_product_is_refused(api):
    facts = api.get(f"/businesses/{MAYA}/financing").json()["facts"]
    over = facts["financing.prd_nano.safe_amount"]["value"] + 5000
    r = api.post(f"/businesses/{MAYA}/financing/applications", json={"product_id": "prd_nano", "amount_minor": over})
    assert r.status_code == 422 and "over_repayment_safe_amount" in r.text
    r = api.post(f"/businesses/{MAYA}/financing/applications", json={"product_id": "prd_digital_line"})
    assert r.status_code == 422 and "product_not_eligible" in r.text
    refused = api.get("/audit", params={"kind": "financing.draft_refused"}).json()["entries"]
    assert sorted(e["data"]["rule"] for e in refused) == ["over_repayment_safe_amount", "product_not_eligible"]
