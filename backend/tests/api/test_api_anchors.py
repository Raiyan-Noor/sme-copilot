"""Anchoring through the API (invariant 9): a signed mandate and an exported Passport are anchored, then verified
offline from recorded chain responses, then tampered with after anchoring, each tamper reported as a mismatch.

The chain is mocked through the record/replay cache (tests/anchor_env.py): anchoring runs in record mode against an
in-memory testnet double; verification runs in a second app in replay mode with no live chain, like CI.
"""

import json
import sqlite3

import pytest

from tests.anchor_env import SimulatedChain, anchor_client, read_log, recording_chain, write_log
from tests.api.conftest import MAYA
from tests.owner_api import enroll, grant

pytestmark = pytest.mark.policy


@pytest.fixture
def anchored(data_dir, seed_dir, tmp_path):
    """Maya signs a reminder mandate and exports her Passport; both end a scenario, so both get anchored."""
    rpc = tmp_path / "rpc"
    live = SimulatedChain()
    client = anchor_client(data_dir, seed_dir, rpc, recording_chain(rpc, live))
    owner = enroll(client, MAYA)
    mandate_id = grant(client, MAYA, owner, "send_invoice_reminder", 20000, ["cus_littlesteps"])["mandate"]["id"]
    exported = client.post(f"/businesses/{MAYA}/passport/export").json()
    return {"client": client, "rpc": rpc, "live": live, "data_dir": data_dir, "seed_dir": seed_dir,
            "mandate_id": mandate_id, "sha": exported["sha256"], "passport": exported["document"]}


def replay_client(a):
    """A fresh app on the same data that can only read recorded chain responses (no network)."""
    return anchor_client(a["data_dir"], a["seed_dir"], a["rpc"])


def test_signing_and_exporting_are_anchored_with_explorer_links(anchored):
    status = anchored["client"].get("/anchors").json()
    assert status["configured"] is True and status["chain_name"] == "Sepolia"
    batches = status["batches"]
    assert [b["status"] for b in batches] == ["confirmed", "confirmed"]
    assert [b["trigger"] for b in batches] == ["passport_exported", "owner_signed"]  # newest first
    kinds = [{leaf["kind"] for leaf in b["leaves"]} for b in batches]
    assert kinds == [{"audit_head", "passport"}, {"audit_head", "mandate"}]
    assert batches[0]["explorer_url"] == f"https://sepolia.etherscan.io/tx/{batches[0]['tx_hash']}"
    assert anchored["live"].txs[batches[0]["tx_hash"]].data_hex == batches[0]["merkle_root"]
    logged = anchored["client"].get("/audit", params={"kind": "anchor.confirmed"}).json()["entries"]
    assert {e["data"]["tx_hash"] for e in logged} == {b["tx_hash"] for b in batches}


def test_anchor_now_with_nothing_new_is_up_to_date(anchored):
    client = anchored["client"]
    assert client.post("/anchors").json()["status"] == "up_to_date"
    client.post("/clock/advance", json={"days": 1, "run_overnight": False})  # a fast-forward ends a scenario
    assert client.get("/anchors").json()["batches"][0]["trigger"] == "scenario_end"


def test_everything_verifies_offline_from_recordings(anchored):
    client = replay_client(anchored)
    status = client.get("/anchors").json()
    assert status["configured"] is False and "replay" in status["reason"]

    verify = client.get("/audit/verify").json()
    assert verify["ok"] is True and verify["onchain"]["ok"] is True
    assert {b["status"] for b in verify["onchain"]["batches"]} == {"match"}

    mandate = client.get(f"/businesses/{MAYA}/gateway/mandates/{anchored['mandate_id']}/onchain").json()
    assert mandate["status"] == "match" and mandate["hash"] == mandate["recorded_hash"]
    assert mandate["onchain"]["explorer_url"].startswith("https://sepolia.etherscan.io/tx/0x")

    passport = client.get(f"/businesses/{MAYA}/passport/exports/{anchored['sha']}/onchain").json()
    assert passport["status"] == "match" and passport["hash"] == anchored["sha"]

    holder = client.post("/anchors/verify/passport", json=anchored["passport"]).json()
    assert holder["status"] == "match" and holder["batch_id"] == passport["batch_id"]


def test_anchor_now_without_a_chain_is_refused_and_logged(anchored):
    client = replay_client(anchored)
    assert client.post("/anchors").json()["status"] == "not_configured"
    assert client.get("/audit", params={"kind": "anchor.refused"}).json()["total"] == 1


# --- tamper after anchoring ----------------------------------------------------------------------------------------

def test_editing_one_audit_line_is_a_mismatch(anchored):
    path = anchored["data_dir"] / "audit.jsonl"
    entries = read_log(path)
    target = next(e for e in entries if e["kind"] == "gateway.mandate_stored")
    target["data"]["expiry"] = "2099-12-31"  # edited in place, hashes left alone
    write_log(path, entries)

    verify = replay_client(anchored).get("/audit/verify").json()
    assert verify["ok"] is False and verify["first_bad_seq"] == target["seq"]
    assert verify["onchain"]["ok"] is False
    assert "mismatch" in {b["status"] for b in verify["onchain"]["batches"]}


def test_editing_one_mandate_is_a_mismatch(anchored):
    db = anchored["data_dir"] / MAYA / "gateway.sqlite"
    with sqlite3.connect(db) as conn:
        doc = json.loads(conn.execute("SELECT document FROM mandates WHERE id = ?",
                                      (anchored["mandate_id"],)).fetchone()[0])
        doc["terms"]["max_amount_minor"] = 50000  # quietly raise the owner's signed cap
        conn.execute("UPDATE mandates SET document = ? WHERE id = ?", (json.dumps(doc), anchored["mandate_id"]))

    check = replay_client(anchored).get(f"/businesses/{MAYA}/gateway/mandates/{anchored['mandate_id']}/onchain").json()
    assert check["status"] == "mismatch"
    assert check["hash"] != check["recorded_hash"]


def test_editing_one_passport_field_is_a_mismatch(anchored):
    path = anchored["data_dir"] / MAYA / "passports" / f"{anchored['sha']}.json"
    doc = json.loads(path.read_bytes())
    doc["band"]["id"] = "ready"
    path.write_bytes(json.dumps(doc, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode())

    client = replay_client(anchored)
    check = client.get(f"/businesses/{MAYA}/passport/exports/{anchored['sha']}/onchain").json()
    assert check["status"] == "mismatch" and check["hash"] != anchored["sha"]
    # A lender handed the edited file: its hash is in no anchored batch.
    holder = client.post("/anchors/verify/passport", json=doc).json()
    assert holder["status"] == "not_anchored"


def test_passport_verifier_rejects_non_canonical_json(anchored):
    r = replay_client(anchored).post("/anchors/verify/passport", json={"score": 0.5})
    assert r.status_code == 422
