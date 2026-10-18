"""Red-team: an insider with write access to the server rewrites the audit log (invariants 7 and 9).

The local chain check alone cannot catch this: the insider recomputes every hash after the edit, so `verify()` on
the file passes. What catches it is the anchor check: the root recomputed from the rewritten log no longer equals
the root in the testnet transaction, which the insider cannot change. Each variant records the rule the on-chain
check returned. The chain is mocked through the record/replay cache (tests/anchor_env.py), so CI stays offline.
"""

import json
import sqlite3

import pytest

from app.anchoring import store_path
from app.anchoring.merkle import build, leaf_hash
from tests.agent_env import MAYA, build_template, copy_data_dir
from tests.anchor_env import SimulatedChain, anchor_client, insider_rewrite, read_log, recording_chain, write_log
from tests.owner_api import approve, enroll, propose, sign_approval

pytestmark = pytest.mark.redteam


@pytest.fixture(scope="module")
def template(tmp_path_factory):
    return build_template(tmp_path_factory.mktemp("anchor-attacks"))


@pytest.fixture
def anchored(template, tmp_path):
    """The owner signs a T3 cancellation; the approval ends a scenario and is anchored."""
    data_dir, seed_dir = template
    data_dir = copy_data_dir(data_dir, tmp_path / "tenants")
    rpc = tmp_path / "rpc"
    client = anchor_client(data_dir, seed_dir, rpc, recording_chain(rpc, SimulatedChain()))
    owner = enroll(client, MAYA)
    approval_id = propose(client, MAYA, "cancel_subscription", subscription_id="sub_pos_b")["approval"]["approval_id"]
    assert approve(client, MAYA, approval_id, owner, sign_approval(client, MAYA, approval_id, owner))["status"] == \
        "executed"
    assert client.get("/anchors").json()["batches"][0]["status"] == "confirmed"
    return data_dir, seed_dir, rpc


def auditor(anchored):
    """Whoever checks the log later: a fresh app, replaying recorded chain responses only."""
    data_dir, seed_dir, rpc = anchored
    return anchor_client(data_dir, seed_dir, rpc)


def caught(attack, verify: dict) -> None:
    assert verify["onchain"]["ok"] is False
    for b in verify["onchain"]["batches"]:
        if b["status"] == "mismatch":
            attack.caught("anchor", b["rule"])


def test_insider_rewrites_a_line_and_recomputes_every_hash(anchored, attack):
    attack("ATK-INSIDER-LOG-REWRITE", "edit one executed action and recompute every later hash", "scripted")
    path = anchored[0] / "audit.jsonl"
    seq = next(e["seq"] for e in read_log(path) if e["kind"] == "executor.executed")
    insider_rewrite(path, seq, lambda e: e["data"].update(tool="send_supplier_message"))

    verify = auditor(anchored).get("/audit/verify").json()
    assert verify["ok"] is True  # the local chain check is fooled
    caught(attack, verify)
    assert attack.data["defenses"] == [{"layer": "anchor", "rule": "audit_head_mismatch"}]


def test_insider_rewrites_the_log_and_the_anchors_record_to_match(anchored, attack):
    attack("ATK-INSIDER-LOG-REWRITE", "rewrite the log and the local anchors record to match it", "scripted")
    data_dir = anchored[0]
    path = data_dir / "audit.jsonl"
    seq = next(e["seq"] for e in read_log(path) if e["kind"] == "gateway.decision")
    insider_rewrite(path, seq, lambda e: e["data"].update(status="denied"))
    entries = {e["seq"]: e["hash"] for e in read_log(path)}
    with sqlite3.connect(store_path(data_dir)) as conn:
        for batch_id, head_seq, leaves_json in conn.execute("SELECT batch_id, head_seq, leaves FROM anchors").fetchall():
            leaves = json.loads(leaves_json)
            for leaf in leaves:
                if leaf["kind"] == "audit_head":
                    leaf["hash"] = entries[head_seq]
                    leaf["leaf_hash"] = leaf_hash("audit_head", leaf["hash"])
            root, _ = build([leaf["leaf_hash"] for leaf in leaves])
            conn.execute("UPDATE anchors SET leaves = ?, head_hash = ?, merkle_root = ? WHERE batch_id = ?",
                         (json.dumps(leaves), entries[head_seq], root, batch_id))

    verify = auditor(anchored).get("/audit/verify").json()
    assert verify["ok"] is True
    caught(attack, verify)
    assert {"layer": "anchor", "rule": "onchain_root_mismatch"} in attack.data["defenses"]


def test_insider_truncates_the_log_behind_the_anchor(anchored, attack):
    attack("ATK-INSIDER-LOG-REWRITE", "delete the anchored tail of the log", "scripted")
    data_dir = anchored[0]
    path = data_dir / "audit.jsonl"
    with sqlite3.connect(store_path(data_dir)) as conn:
        first_head = min(r[0] for r in conn.execute("SELECT head_seq FROM anchors"))
    write_log(path, [e for e in read_log(path) if e["seq"] < first_head])

    verify = auditor(anchored).get("/audit/verify").json()
    assert verify["ok"] is True  # what is left is a valid chain
    caught(attack, verify)
    assert {"layer": "anchor", "rule": "anchored_entry_missing"} in attack.data["defenses"]
