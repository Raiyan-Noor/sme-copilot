"""Custom skills over the API (feature plan P8): the built-in list, upload and preview, onboarding with an uploaded
skill, audit entries and the anchoring leaf. Attack cases are in tests/redteam/test_skill_attacks.py."""

from pathlib import Path

from app.packs.loader import SKILLS_DIR
from app.packs.skill import skill_sha256
from tests.anchor_env import SimulatedChain, anchor_client, recording_chain

BAKERY = SKILLS_DIR / "bakery.skill.md"
SAMPLES = Path(__file__).resolve().parents[2] / "data" / "samples" / "fashion_shop"


def preview(api, path: Path = BAKERY, data: bytes | None = None) -> dict:
    r = api.post("/skills/preview", files={"file": (path.name, data if data is not None else path.read_bytes())})
    assert r.status_code == 200, r.text
    return r.json()


def start(api, **body) -> dict:
    r = api.post("/onboarding", json={"name": "Crumb Corner", "business_type": "a bakery", **body})
    assert r.status_code == 200, r.text
    return r.json()


def audit(api, kind: str) -> list[dict]:
    return api.get("/audit", params={"kind": kind}).json()["entries"]


def test_builtin_skills_are_listed_verified(api):
    skills = api.get("/skills").json()
    assert [s["pack_id"] for s in skills] == ["fashion_retail", "grocery_retail", "general_retail"]
    assert all(s["badge"] == "verified" and s["builtin"] and s["status"] == "ok" for s in skills)
    fashion = skills[0]
    assert fashion["display_name"] == "Fashion" and fashion["description"].startswith("# Fashion")
    assert "ad_spend" in [n["kind"] for n in fashion["data_needs"]]
    assert "product_returns" in [d["detector"] for d in fashion["detectors"]]


def test_bakery_preview_shows_what_it_asks_and_watches(api):
    p = preview(api)
    assert p["status"] == "ok" and p["badge"] == "community" and not p["builtin"]
    assert p["sha256"] == skill_sha256(BAKERY.read_text(encoding="utf-8"))
    assert p["display_name"] == "Bakery" and p["errors"] == [] and p["notices"] == []
    assert [q["id"] for q in p["questions"]][:2] == ["unsold_bake", "cake_deposits"]
    assert p["questions"][0]["why"].startswith("Unsold bread")
    assert {k["id"] for k in p["kpis"]} >= {"gross_margin", "waste_share", "buffer_days"}
    entry = audit(api, "skill.uploaded")[-1]["data"]
    assert entry == {"sha256": p["sha256"], "pack_id": "bakery", "version": 1, "badge": "community",
                     "builtin": False, "notices": 0, "bytes": BAKERY.stat().st_size}


def test_bakery_drives_different_onboarding_questions(api):
    p = preview(api)
    biz = start(api, skill_sha256=p["sha256"])
    assert biz["pack_id"] == "bakery"
    view = api.get(f"/businesses/{biz['id']}/onboarding").json()
    assert [q["id"] for q in view["plan"]["questions"]] == [q["id"] for q in p["questions"]]
    grocery = start(api, business_type="a grocery")
    other = api.get(f"/businesses/{grocery['id']}/onboarding").json()
    assert {q["id"] for q in other["plan"]["questions"]}.isdisjoint({"unsold_bake", "cake_deposits"})
    # The bakery questions work end to end: the answer is stored and the engine computes with the skill.
    r = api.post(f"/businesses/{biz['id']}/onboarding/answers", json={"question_id": "unsold_bake", "option": 2})
    assert r.status_code == 200, r.text
    with (SAMPLES / "bank.csv").open("rb") as f:
        up = api.post(f"/businesses/{biz['id']}/onboarding/uploads", files={"file": ("bank.csv", f.read())}).json()
    assert up["status"] == "imported"
    kpis = api.get(f"/businesses/{biz['id']}/kpis")
    assert kpis.status_code == 200, kpis.text
    assert "waste_share" in kpis.text  # the bakery's own KPI, computed by the engine
    created = next(e["data"] for e in audit(api, "onboarding.business_created")
                   if e["data"]["business_id"] == biz["id"])
    assert created["custom_skill"] == p["sha256"] and created["skill_chosen"] is True
    assert audit(api, "skill.activated")[-1]["data"]["sha256"] == p["sha256"]


def test_picking_a_builtin_overrides_the_words(api):
    biz = start(api, business_type="grocery corner store", pack_id="fashion_retail")
    assert biz["pack_id"] == "fashion_retail"
    r = api.post("/onboarding", json={"name": "X", "business_type": "y", "pack_id": "../gateway/policy"})
    assert r.status_code == 422


def test_uploading_a_builtin_file_uses_the_builtin(api):
    p = preview(api, SKILLS_DIR / "grocery.skill.md")
    assert p["badge"] == "verified" and p["builtin"]
    biz = start(api, skill_sha256=p["sha256"])
    assert biz["pack_id"] == "grocery_retail"
    assert audit(api, "skill.activated") == []


def test_malformed_skill_is_rejected_with_clear_errors(api):
    bad = BAKERY.read_text(encoding="utf-8").replace("benchmarks_synthetic: true", "benchmarks_synthetic: true\nflavour: x")
    p = preview(api, data=bad.encode())
    assert p["status"] == "rejected" and p["sha256"] is None
    assert p["errors"] == ["flavour: unknown field: it is not part of the skill format"]
    assert audit(api, "skill.rejected")[-1]["data"]["first_errors"] == p["errors"]


def test_unknown_staged_skill_is_refused(api):
    r = api.post("/onboarding", json={"name": "X", "business_type": "y", "skill_sha256": "0" * 64})
    assert r.status_code == 422 and "upload it again" in r.json()["detail"]


def test_uploaded_skill_hash_is_an_anchoring_leaf(data_dir, seed_dir, tmp_path):
    rpc = tmp_path / "rpc"
    client = anchor_client(data_dir, seed_dir, rpc, recording_chain(rpc, SimulatedChain()))
    p = preview(client)
    assert client.post("/anchors").json()["status"] in ("queued", "confirmed")
    leaves = [leaf for b in client.get("/anchors").json()["batches"] for leaf in b["leaves"]]
    assert ("skill", p["sha256"]) in [(x["kind"], x["hash"]) for x in leaves]


def test_reset_clears_staged_uploads(api):
    p = preview(api)
    assert api.post("/onboarding/reset").status_code == 200
    r = api.post("/onboarding", json={"name": "X", "business_type": "y", "skill_sha256": p["sha256"]})
    assert r.status_code == 422
