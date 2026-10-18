"""Anchoring test helpers: an in-memory testnet double, an app whose chain goes through the record/replay cache, and
an insider who rewrites the audit log.

How the RPC is mocked (CI has no network): a test first runs in `record` mode with `SimulatedChain` playing the
live testnet, which writes its responses into a temporary replay directory (namespace `rpc`). It then opens a
second app on the same data in `replay` mode with no live chain at all, so every on-chain read comes from those
recordings, exactly as CI replays the real Sepolia recordings made by `make anchor`.

`SimulatedChain` is a test double only. Its transactions are not real and never appear in evidence (invariant 8).
"""

import hashlib
import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.anchoring.chain import AnchorTx, CachedChain, ChainError, OnchainTx
from app.audit.canonical import canonical_hash
from app.llm.cache import RequestCache
from app.main import PASSCODE_HEADER, create_app
from tests.helpers import TEST_PASSCODE, make_settings

SEPOLIA = 11155111
SIM_ADDRESS = "0x" + "5e" * 20


class SimulatedChain:
    """An in-memory stand-in for a testnet that records 0-value self-transactions. `fail` makes the next N sends
    raise like an RPC outage."""

    def __init__(self, chain_id: int = SEPOLIA, fail: int = 0):
        self.chain_id = chain_id
        self.fail = fail
        self.sends = 0
        self.block = 7_000_000
        self.txs: dict[str, OnchainTx] = {}

    @property
    def can_send(self) -> bool:
        return True

    def send_anchor(self, root_hex: str) -> AnchorTx:
        self.sends += 1
        if self.fail > 0:
            self.fail -= 1
            raise ChainError("RPC call failed (ConnectionError)")
        self.block += 1
        tx_hash = "0x" + hashlib.sha256(f"{self.chain_id}:{self.block}:{root_hex}".encode()).hexdigest()
        stamp = 1_760_000_000 + 12 * (self.block - 7_000_000)
        self.txs[tx_hash] = OnchainTx(tx_hash=tx_hash, chain_id=self.chain_id, from_address=SIM_ADDRESS,
                                      to_address=SIM_ADDRESS, value_wei=0, data_hex=root_hex,
                                      block_number=self.block, block_timestamp=stamp, succeeded=True)
        return AnchorTx(tx_hash=tx_hash, chain_id=self.chain_id, from_address=SIM_ADDRESS, block_number=self.block,
                        block_timestamp=stamp)

    def get_tx(self, tx_hash: str) -> OnchainTx:
        if tx_hash not in self.txs:
            raise ChainError("transaction not found on chain")
        return self.txs[tx_hash]


def recording_chain(rpc_dir: Path, live: SimulatedChain | None = None) -> CachedChain:
    """`live` behind the cache in record mode: what the 'testnet' returns is written to `rpc_dir`."""
    return CachedChain(RequestCache(rpc_dir, "record"), SEPOLIA, live or SimulatedChain())


def anchor_client(data_dir: Path, seed_dir: Path, rpc_dir: Path, chain: CachedChain | None = None,
                  **overrides) -> TestClient:
    """An app with synchronous anchoring. With `chain`, it anchors through it; without, it is a replay-mode app that
    can only read recorded chain responses from `rpc_dir` (no network, like CI)."""
    values = {"data_dir": data_dir, "seed_dir": seed_dir, "anchor_replay_dir": rpc_dir, "anchor_background": False,
              "anchor_batch_size": 1000, "anchor_replay": "record" if chain else "replay"}
    values.update(overrides)
    app = create_app(make_settings(**values), anchor_chain=chain)
    return TestClient(app, headers={PASSCODE_HEADER: TEST_PASSCODE})


def read_log(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_log(path: Path, entries: list[dict]) -> None:
    path.write_text("".join(json.dumps(e, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"
                            for e in entries), encoding="utf-8")


def insider_rewrite(path: Path, seq: int, mutate) -> None:
    """What an insider with write access does: change entry `seq`, then recompute its hash and every later link and
    hash, so the local chain check passes again."""
    entries = read_log(path)
    mutate(entries[seq])
    prev = entries[seq]["prev_hash"]
    for e in entries[seq:]:
        e["prev_hash"] = prev
        e["hash"] = canonical_hash({k: v for k, v in e.items() if k != "hash"})
        prev = e["hash"]
    write_log(path, entries)
