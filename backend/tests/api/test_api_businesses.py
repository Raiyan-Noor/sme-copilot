"""Businesses, Skill Pack switch, auth on every route, and tenant isolation of IDs."""

from fastapi.testclient import TestClient

from tests.api.conftest import LINA, MAYA, api_client


def test_lists_both_seed_businesses(read_api):
    r = read_api.get("/businesses")
    assert r.status_code == 200
    by_id = {b["id"]: b for b in r.json()}
    assert set(by_id) == {MAYA, LINA}
    assert by_id[MAYA]["name"] == "Maya's Corner Store" and by_id[MAYA]["pack_id"] == "grocery_retail"
    assert by_id[LINA]["pack_id"] == "fashion_retail"
    assert all(b["synthetic"] for b in by_id.values())


def test_business_detail_shows_tokens_not_account_numbers(read_api):
    r = read_api.get(f"/businesses/{MAYA}")
    assert r.status_code == 200
    body = r.json()
    assert body["transactions"] > 0 and body["scheduled_items"] > 0
    ids = [a["id"] for a in body["accounts"]]
    assert len(ids) == 3
    assert all(i.startswith(("acct_", "book_")) for i in ids)
    assert "4410" not in r.text and "7781" not in r.text  # seed account numbers never come back


def test_every_business_route_requires_the_passcode(template_data_dir, seed_dir):
    anon = api_client(template_data_dir, seed_dir)
    anon.headers.pop("X-Passcode")
    for path in ("/businesses", f"/businesses/{MAYA}/cash", "/audit", "/clock", "/packs"):
        assert anon.get(path).status_code == 401, path
    assert anon.post("/clock/advance", json={"days": 1}).status_code == 401


def test_unknown_and_malformed_business_ids_are_404(read_api):
    assert read_api.get("/businesses/no-such-shop").status_code == 404
    assert read_api.get("/businesses/..%2F..%2Fetc").status_code == 404
    assert read_api.get("/businesses/BAD_ID/cash").status_code == 404


def test_packs_are_listed_with_synthetic_benchmarks(read_api):
    packs = {p["id"]: p for p in read_api.get("/packs").json()}
    assert set(packs) == {"grocery_retail", "fashion_retail", "general_retail"}
    assert all(p["benchmarks_synthetic"] for p in packs.values())


def test_pack_switch_changes_categories_and_kpis(api: TestClient):
    before_kpis = {k["kpi_id"] for k in api.get(f"/businesses/{MAYA}/kpis").json()["kpis"]}
    before_txn = api.get(f"/businesses/{MAYA}/transactions", params={"limit": 500}).json()

    r = api.put(f"/businesses/{MAYA}/pack", json={"pack_id": "fashion_retail"})
    assert r.status_code == 200 and r.json()["pack_id"] == "fashion_retail"

    after_kpis = api.get(f"/businesses/{MAYA}/kpis").json()
    assert after_kpis["pack_ref"] == "pack:fashion_retail@1"
    assert {k["kpi_id"] for k in after_kpis["kpis"]} != before_kpis
    after_txn = api.get(f"/businesses/{MAYA}/transactions", params={"limit": 500}).json()
    assert after_txn["pack_ref"] == "pack:fashion_retail@1"
    assert [t["category"] for t in after_txn["items"]] != [t["category"] for t in before_txn["items"]]

    switches = api.get("/audit", params={"kind": "business.pack_switched"}).json()["entries"]
    assert switches[0]["data"] == {"business_id": MAYA, "from": "grocery_retail", "to": "fashion_retail"}


def test_unknown_pack_is_rejected_and_nothing_changes(api):
    r = api.put(f"/businesses/{MAYA}/pack", json={"pack_id": "../../etc/passwd"})
    assert r.status_code == 422
    assert api.get(f"/businesses/{MAYA}").json()["pack_id"] == "grocery_retail"
