"""Trust routes: limits mirror policy.yaml and the owner's signed standing mandates; red-team results pass through."""

import json

from fastapi.testclient import TestClient

from app.gateway.policy import load_policy
from tests.api.conftest import MAYA, api_client
from tests.owner_api import enroll, grant


def test_limits_mirror_policy_yaml(read_api: TestClient):
    r = read_api.get(f"/businesses/{MAYA}/limits")
    assert r.status_code == 200, r.text
    body = r.json()
    policy = load_policy()
    assert {t["tool"] for t in body["t2"]} == set(policy.t2)
    assert {t["tool"] for t in body["t3"]} == set(policy.t3)
    assert body["t1_tools"] == list(policy.t1_patterns)
    assert body["t4_categories"] == list(policy.t4_categories)
    for t2 in body["t2"]:
        assert t2["policy_max_amount_minor"] == policy.t2[t2["tool"]].max_amount_minor
    oob = {t["tool"]: t["requires_out_of_band_call_script"] for t in body["t3"]}
    assert oob["change_payee_details"] is True


def test_reminder_candidates_are_customers_from_trusted_schedules(read_api: TestClient):
    body = read_api.get(f"/businesses/{MAYA}/limits").json()
    reminders = next(t for t in body["t2"] if t["tool"] == "send_invoice_reminder")
    assert reminders["active"] is None
    assert reminders["candidates"], "seed data has customer receivables"
    assert all(c["id"] for c in reminders["candidates"])


def test_signed_standing_mandate_shows_as_active(api: TestClient):
    owner = enroll(api, MAYA)
    body = api.get(f"/businesses/{MAYA}/limits").json()
    assert body["owner_key_enrolled"] is True
    reminders = next(t for t in body["t2"] if t["tool"] == "send_invoice_reminder")
    customers = [c["id"] for c in reminders["candidates"]]
    result = grant(api, MAYA, owner, "send_invoice_reminder", 20000, customers)

    reminders = next(t for t in api.get(f"/businesses/{MAYA}/limits").json()["t2"]
                     if t["tool"] == "send_invoice_reminder")
    assert reminders["active"]["mandate_id"] == result["mandate"]["id"]
    assert reminders["active"]["max_amount_minor"] == 20000
    assert reminders["active"]["allowlist"] == customers


def test_redteam_results_pass_through_unchanged(data_dir, seed_dir, tmp_path):
    report = {"schema": "redteam_results/v1", "generated_by": "make redteam", "mode": "replay",
              "pending_attacks": {}, "providers": {
                  "openai": {"status": "ran", "attacks_run": 3, "attacks_blocked": 3, "tasks_run": 2,
                             "tasks_succeeded": 1, "attacks": [{"id": "ATK-X", "name": "X", "blocked": True,
                                                                "caught_by": [{"layer": "gateway", "rule": "r",
                                                                               "variants": 1}]}]},
                  "gemini": {"status": "not_run", "reason": "no recordings"}}}
    path = tmp_path / "redteam.json"
    path.write_text(json.dumps(report), encoding="utf-8")
    client = api_client(data_dir, seed_dir, redteam_results=path)
    body = client.get("/redteam").json()
    assert body["providers"]["openai"]["attacks_blocked"] == 3
    assert body["providers"]["openai"]["tasks_succeeded"] == 1
    assert body["providers"]["openai"]["attacks"][0]["caught_by"][0]["layer"] == "gateway"
    assert body["providers"]["gemini"]["status"] == "not_run"


def test_redteam_is_404_until_the_suite_has_run(data_dir, seed_dir, tmp_path):
    client = api_client(data_dir, seed_dir, redteam_results=tmp_path / "missing.json")
    assert client.get("/redteam").status_code == 404
