"""`make anchor`: anchor now against the live testnet, verify it back from the chain, write docs/results/anchors.json.

Manual only (invariant 9). Needs ANCHOR_RPC_URL and a faucet-funded throwaway ANCHOR_PRIVATE_KEY in .env; the chain
ID must be an allow-listed testnet (Sepolia 11155111 or Base Sepolia 84532). It runs in record mode: the chain's
responses are saved under backend/data/replay/rpc/, so CI can re-verify these exact transactions with no network.

It works on the dev data (backend/data/tenants) and appends to its audit log, so it refuses to run while the dev API
is up on :8000 (two processes appending to one hash chain would fork it); use the "Anchor now" button instead then.

Everything in anchors.json comes from this run: tx hashes, blocks and the match/mismatch result are what the chain
returned (invariant 8). Only hashes are anchored; the file holds hashes, proofs and references, never business data.
"""

import json
import socket
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "results" / "anchors.json"
sys.path.insert(0, str(ROOT / "backend"))


def api_running(port: int = 8000) -> bool:
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


def main() -> int:
    from app.anchoring.service import CHAIN_NAMES
    from app.config import get_settings
    from app.services.runtime import Runtime

    if api_running():
        print("make anchor: the dev API is running on :8000; stop it first, or use Anchor now on the Trust screen.")
        return 1
    settings = get_settings().model_copy(update={"anchor_replay": "record", "anchor_background": False})
    rt = Runtime(settings)
    anchors = rt.anchors
    if not anchors.configured:
        print(f"make anchor: not configured: {anchors.status().reason}")
        return 1

    result = anchors.request("manual", manual=True)
    if result.status == "already_queued":
        result = anchors.request("manual", manual=True)  # a batch left queued earlier: retry it now
    print(f"make anchor: {result.status}" + (f" ({result.batch.batch_id})" if result.batch else ""))
    if result.batch and result.batch.status != "confirmed":
        print(f"make anchor: not confirmed yet: {result.batch.last_error}")
        return 1

    check = anchors.verify_log()
    batches = [b for b in anchors.store.all() if b.status == "confirmed"]
    results = {c.batch_id: c for c in check.batches}
    doc = {
        "schema": "anchors/v1",
        "generated_by": "make anchor (scripts/anchor.py)",
        "data": "synthetic (Maya's Corner Store, Lina's Boutique)",
        "chain_id": settings.anchor_chain_id,
        "chain_name": CHAIN_NAMES.get(settings.anchor_chain_id),
        "explorer_base_url": anchors.explorer_url,
        "merkle": "index-based SHA-256; leaf = H(0x00 || '<kind>:<hash>'), node = H(0x01 || left || right); "
                  "odd node promoted unchanged (backend/app/anchoring/merkle.py)",
        "verified_log_ok": check.ok,
        "batches": [{
            "batch_id": b.batch_id, "trigger": b.trigger, "merkle_root": b.merkle_root, "tx_hash": b.tx_hash,
            "explorer_url": anchors.explorer(b.tx_hash), "chain_id": b.chain_id, "from_address": b.from_address,
            "block_number": b.block_number, "block_timestamp": b.block_timestamp, "head_seq": b.head_seq,
            "leaves": [leaf.model_dump(mode="json") for leaf in b.leaves],
            "verification": results[b.batch_id].status if b.batch_id in results else "not_checked",
        } for b in batches],
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    for b in doc["batches"]:
        print(f"  {b['batch_id']}  block {b['block_number']}  {b['verification']}  {b['explorer_url']}")
    print(f"make anchor: on-chain check of the log: {check.ok}; wrote {OUT.relative_to(ROOT)}")
    return 0 if check.ok else 1


if __name__ == "__main__":
    sys.exit(main())
