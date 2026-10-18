"""The `anchors` record: one row per batch, in data_dir/_anchoring/anchors.sqlite beside the audit log it anchors.

A batch keeps everything a verifier needs without the server: the Merkle root, every leaf with its kind, hash and
proof, the transaction that published the root and where it landed. Rows are only ever inserted, then moved
`queued -> sent -> confirmed`; an anchored root is never edited. Nothing here is trusted by the verifier on its own:
verification recomputes leaves from the log, mandates and Passports, and compares against the root on chain.
"""

import json
import sqlite3
import threading
from datetime import date
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from app.anchoring.merkle import LeafKind, ProofStep

BatchStatus = Literal["queued", "sent", "confirmed"]

SCHEMA = """
CREATE TABLE IF NOT EXISTS anchors (
    batch_id TEXT PRIMARY KEY,
    trigger TEXT NOT NULL,
    merkle_root TEXT NOT NULL,
    leaves TEXT NOT NULL,
    head_seq INTEGER NOT NULL,
    head_hash TEXT NOT NULL,
    created_on TEXT NOT NULL,
    status TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    tx_hash TEXT,
    chain_id INTEGER NOT NULL,
    from_address TEXT,
    block_number INTEGER,
    block_timestamp INTEGER
);
"""


class Leaf(BaseModel):
    """One anchored hash. `ref` says where it came from (audit seq, mandate ID, Passport export), never its content."""

    kind: LeafKind
    hash: str
    ref: str
    leaf_hash: str
    proof: list[ProofStep]


class AnchorBatch(BaseModel):
    batch_id: str
    trigger: str
    merkle_root: str
    leaves: list[Leaf]
    head_seq: int
    head_hash: str
    created_on: date  # simulated date the batch was cut
    status: BatchStatus
    attempts: int
    last_error: str | None
    tx_hash: str | None
    chain_id: int
    from_address: str | None
    block_number: int | None
    block_timestamp: int | None  # unix seconds of the block that holds the root


_COLUMNS = list(AnchorBatch.model_fields)


class AnchorStore:
    def __init__(self, path: Path | str):
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        self._lock = threading.Lock()
        self._conn.executescript(SCHEMA)

    def _row(self, row: tuple) -> AnchorBatch:
        values = dict(zip(_COLUMNS, row))
        values["leaves"] = json.loads(values["leaves"])
        return AnchorBatch(**values)

    def _select(self, where: str = "1", params: tuple = ()) -> list[AnchorBatch]:
        rows = self._conn.execute(
            f"SELECT {', '.join(_COLUMNS)} FROM anchors WHERE {where} ORDER BY batch_id", params).fetchall()
        return [self._row(r) for r in rows]

    def next_batch_id(self) -> str:
        n = self._conn.execute("SELECT COUNT(*) FROM anchors").fetchone()[0]
        return f"anc-{n + 1:06d}"

    def add(self, batch: AnchorBatch) -> None:
        values = batch.model_dump(mode="json")
        values["leaves"] = json.dumps(values["leaves"], sort_keys=True)
        with self._lock:
            self._conn.execute(
                f"INSERT INTO anchors ({', '.join(_COLUMNS)}) VALUES ({', '.join('?' for _ in _COLUMNS)})",
                [values[c] for c in _COLUMNS])

    def mark_attempt(self, batch_id: str, error: str | None) -> None:
        with self._lock:
            self._conn.execute("UPDATE anchors SET attempts = attempts + 1, last_error = ? WHERE batch_id = ?",
                               (error, batch_id))

    def mark_sent(self, batch_id: str, tx_hash: str) -> None:
        with self._lock:
            self._conn.execute("UPDATE anchors SET status = 'sent', tx_hash = ? WHERE batch_id = ? AND status = 'queued'",
                               (tx_hash, batch_id))

    def mark_confirmed(self, batch_id: str, tx_hash: str, from_address: str, block_number: int,
                       block_timestamp: int) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE anchors SET status = 'confirmed', last_error = NULL, tx_hash = ?, from_address = ?,"
                " block_number = ?, block_timestamp = ? WHERE batch_id = ? AND status != 'confirmed'",
                (tx_hash, from_address, block_number, block_timestamp, batch_id))

    def get(self, batch_id: str) -> AnchorBatch | None:
        found = self._select("batch_id = ?", (batch_id,))
        return found[0] if found else None

    def all(self) -> list[AnchorBatch]:
        """Every batch, oldest first."""
        return self._select()

    def unconfirmed(self) -> list[AnchorBatch]:
        return self._select("status != 'confirmed'")

    def latest(self) -> AnchorBatch | None:
        found = self._select()
        return found[-1] if found else None

    def find(self, kind: str, value_hex: str) -> list[tuple[AnchorBatch, Leaf]]:
        """Every batch holding a leaf of `kind` with hash `value_hex`, oldest first."""
        out = []
        for batch in self._select("leaves LIKE ?", (f"%{value_hex}%",)):
            out.extend((batch, leaf) for leaf in batch.leaves if leaf.kind == kind and leaf.hash == value_hex)
        return out
