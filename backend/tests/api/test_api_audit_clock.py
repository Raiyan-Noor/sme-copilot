"""Audit log read/verify/export over HTTP, tamper detection, and the simulated clock (forward only, persisted)."""

import json

from tests.api.conftest import MAYA, api_client


def test_audit_page_is_newest_first(api):
    api.post("/clock/advance", json={"days": 1, "run_overnight": False})
    api.post("/clock/advance", json={"days": 2, "run_overnight": False})
    page = api.get("/audit", params={"limit": 2}).json()
    assert [e["kind"] for e in page["entries"]] == ["clock.advanced", "clock.advanced"]
    assert page["entries"][0]["data"]["days"] == 2
    assert page["head"]["seq"] == page["entries"][0]["seq"] and page["head"]["hash"] == page["entries"][0]["hash"]
    seeded = api.get("/audit", params={"kind": "ledger.tenant_seeded"}).json()
    assert seeded["total"] == 2 and all(e["data"]["synthetic"] for e in seeded["entries"])


def test_verify_detects_tampering(api, data_dir):
    api.post("/clock/advance", json={"days": 1})
    assert api.get("/audit/verify").json()["ok"] is True
    path = data_dir / "audit.jsonl"
    lines = path.read_text(encoding="utf-8").splitlines()
    entry = json.loads(lines[0])
    entry["data"]["transactions"] += 1
    lines[0] = json.dumps(entry, sort_keys=True, separators=(",", ":"))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    result = api.get("/audit/verify").json()
    assert result["ok"] is False and result["first_bad_seq"] == 0


def test_export_returns_the_verified_log(api):
    api.get(f"/businesses/{MAYA}/cash")
    head = api.get("/audit/head").json()
    r = api.get("/audit/export")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/x-ndjson")
    assert r.headers["x-audit-verified"] == "true" and r.headers["x-audit-head-hash"] == head["hash"]
    lines = r.text.strip().splitlines()
    assert len(lines) == head["seq"] + 1 and json.loads(lines[-1])["hash"] == head["hash"]
    assert api.get("/audit", params={"limit": 1}).json()["entries"][0]["kind"] == "audit.exported"


def test_clock_reads_and_advances(api):
    assert api.get("/clock").json() == {"today": "2026-10-19", "start": "2026-10-19", "offset_days": 0}
    moved = api.post("/clock/advance", json={"days": 7, "run_overnight": False}).json()
    assert moved == {"today": "2026-10-26", "start": "2026-10-19", "offset_days": 7, "overnight": []}
    logged = api.get("/audit", params={"kind": "clock.advanced"}).json()["entries"][0]
    assert logged["data"] == {"from": "2026-10-19", "to": "2026-10-26", "days": 7}
    assert logged["date"] == "2026-10-26"


def test_clock_never_moves_backwards(api):
    for days in (0, -1, 366):
        assert api.post("/clock/advance", json={"days": days}).status_code == 422
    assert api.get("/clock").json()["offset_days"] == 0


def test_clock_survives_a_restart(api, data_dir, seed_dir):
    api.post("/clock/advance", json={"days": 5})
    restarted = api_client(data_dir, seed_dir)
    assert restarted.get("/clock").json()["today"] == "2026-10-24"
    assert restarted.get("/audit/verify").json()["ok"] is True
