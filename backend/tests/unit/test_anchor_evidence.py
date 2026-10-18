"""The live anchoring evidence (docs/results/anchors.json, written by `make anchor`) re-verified offline in CI
(invariants 8 and 9).

`make anchor` records what the testnet returned under backend/data/replay/rpc/. Here every anchored batch is checked
against those recordings with no network: each proof folds its leaf into the batch root, and the transaction the
chain returned is a confirmed 0-value self-transaction on an allow-listed testnet whose data is exactly that root.
Skipped until the first live run.
"""

import json
from pathlib import Path

import pytest

from app.anchoring.chain import CachedChain
from app.anchoring.merkle import ProofStep, build, leaf_hash, verify_proof
from app.config import ANCHOR_CHAIN_ALLOWLIST
from app.llm.cache import RequestCache

ROOT = Path(__file__).resolve().parents[3]
EVIDENCE = ROOT / "docs" / "results" / "anchors.json"
REPLAY = ROOT / "backend" / "data" / "replay"

pytestmark = pytest.mark.skipif(not EVIDENCE.is_file(), reason="no live anchors yet: run `make anchor`")


def batches() -> list[dict]:
    return json.loads(EVIDENCE.read_text(encoding="utf-8"))["batches"]


def test_evidence_holds_at_least_one_real_anchor():
    doc = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    assert doc["chain_id"] in ANCHOR_CHAIN_ALLOWLIST
    assert doc["verified_log_ok"] is True
    assert any(b["tx_hash"] and b["verification"] == "match" for b in doc["batches"])


@pytest.mark.parametrize("batch", batches() if EVIDENCE.is_file() else [], ids=lambda b: b["batch_id"])
def test_anchored_batch_verifies_from_recorded_chain_data(batch):
    leaves = [leaf_hash(leaf["kind"], leaf["hash"]) for leaf in batch["leaves"]]
    root, _ = build(leaves)
    assert root == batch["merkle_root"]
    for leaf, h in zip(batch["leaves"], leaves):
        assert leaf["leaf_hash"] == h
        assert verify_proof(h, [ProofStep(**s) for s in leaf["proof"]], root)

    chain = CachedChain(RequestCache(REPLAY, "replay"), batch["chain_id"])
    tx = chain.get_tx(batch["tx_hash"])
    assert tx.data_hex == root
    assert tx.value_wei == 0 and tx.to_address.lower() == tx.from_address.lower()
    assert tx.chain_id == batch["chain_id"] and tx.block_number == batch["block_number"] and tx.succeeded
