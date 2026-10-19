"""Append-only, hash-chained JSONL audit log (invariant 7).

Each line is one entry: `{seq, date, time?, kind, data, prev_hash, hash}`. `hash` is the SHA-256 of the canonical JSON
of the entry without `hash`, and `prev_hash` is the previous entry's `hash` (64 zeros for the first). Editing,
inserting, deleting or reordering any line breaks the chain from that point, which `verify()` reports.

A local verify cannot catch an insider who rewrites the file and recomputes every hash; that is what on-chain
anchoring of `head()` is for (invariant 9). Anchoring plugs in through `subscribe()`, which is called after every
append with the new entry, and through `head()`, without changes to this module.

The file is only ever opened in append mode. Dates come from the simulated clock, so logs are replayable. `time`
(HH:MM:SS) is the simulated time of day when the clock has one (`SimClock.now()`); it is hashed like every other
field. Entries written without it (a `FixedClock`, or a log from before it existed) leave the key out entirely, so
their hashes are unchanged.
"""

import json
import shutil
import threading
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.audit.canonical import canonical_hash
from app.clock import Clock

GENESIS_HASH = "0" * 64
_REQUIRED_FIELDS = frozenset({"seq", "date", "kind", "data", "prev_hash", "hash"})


class AuditEntry(BaseModel):
    model_config = ConfigDict(frozen=True)

    seq: int
    date: str
    time: str | None = None
    kind: str
    data: dict[str, Any]
    prev_hash: str
    hash: str

    def body(self) -> dict[str, Any]:
        """The hashed part: everything except `hash` (and `time` when the entry has none)."""
        return self.model_dump(exclude={"hash"} if self.time is not None else {"hash", "time"})


class Head(BaseModel):
    """The chain head: what gets anchored. `seq` is -1 and `hash` is GENESIS_HASH for an empty log."""

    seq: int
    hash: str


class VerifyResult(BaseModel):
    ok: bool
    entries: int
    head: Head
    first_bad_seq: int | None = None
    reason: str | None = None


def entry_hash(body: dict[str, Any]) -> str:
    return canonical_hash(body)


class AuditLog:
    """One hash-chained JSONL file. Thread-safe for appends within one process."""

    def __init__(self, path: Path, clock: Clock):
        self.path = Path(path)
        self.clock = clock
        self._lock = threading.Lock()
        self._subscribers: list[Callable[[AuditEntry], None]] = []
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.touch(exist_ok=True)
        self._head = self._read_head()

    def _read_head(self) -> Head:
        last = None
        for last in self._lines():
            pass
        if last is None:
            return Head(seq=-1, hash=GENESIS_HASH)
        entry = json.loads(last)
        return Head(seq=entry["seq"], hash=entry["hash"])

    def _lines(self) -> Iterator[str]:
        with self.path.open("r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    yield line

    def append(self, kind: str, data: dict[str, Any] | None = None) -> AuditEntry:
        """Append one entry and return it. The only write path to the log (invariant 7)."""
        with self._lock:
            body = {
                "seq": self._head.seq + 1,
                "date": self.clock.today().isoformat(),
                "kind": kind,
                "data": data or {},
                "prev_hash": self._head.hash,
            }
            now = getattr(self.clock, "now", None)
            if now is not None:
                body["time"] = now().strftime("%H:%M:%S")
            entry = AuditEntry(**body, hash=entry_hash(body))
            line = json.dumps({**body, "hash": entry.hash}, sort_keys=True, separators=(",", ":"),
                              ensure_ascii=False)
            with self.path.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
            self._head = Head(seq=entry.seq, hash=entry.hash)
            subscribers = list(self._subscribers)
        for callback in subscribers:
            callback(entry)
        return entry

    def head(self) -> Head:
        """Current head (latest seq and hash); the value anchoring publishes."""
        return self._head

    def subscribe(self, callback: Callable[[AuditEntry], None]) -> None:
        """Call `callback(entry)` after every append (outside the lock). Used by anchoring's batch trigger."""
        self._subscribers.append(callback)

    def entries(self) -> list[AuditEntry]:
        return [AuditEntry(**json.loads(line)) for line in self._lines()]

    def verify(self) -> VerifyResult:
        """Recompute every hash and link from the file. Reports the first entry that breaks the chain."""
        prev = GENESIS_HASH
        count = 0
        head = Head(seq=-1, hash=GENESIS_HASH)
        for expected_seq, line in enumerate(self._lines()):
            count += 1
            try:
                raw = json.loads(line)
                entry = AuditEntry(**raw)
            except Exception as exc:  # malformed line is tampering too
                return self._bad(count, head, expected_seq, f"unparseable entry: {exc.__class__.__name__}")
            if set(raw) - {"time"} != _REQUIRED_FIELDS:
                return self._bad(count, head, expected_seq, "unexpected or missing fields")
            if entry.seq != expected_seq:
                return self._bad(count, head, expected_seq, f"sequence gap: expected {expected_seq}, got {entry.seq}")
            if entry.prev_hash != prev:
                return self._bad(count, head, expected_seq, "prev_hash does not match the previous entry")
            if entry_hash(entry.body()) != entry.hash:
                return self._bad(count, head, expected_seq, "entry hash does not match its contents")
            prev = entry.hash
            head = Head(seq=entry.seq, hash=entry.hash)
        return VerifyResult(ok=True, entries=count, head=head)

    @staticmethod
    def _bad(count: int, head: Head, seq: int, reason: str) -> VerifyResult:
        return VerifyResult(ok=False, entries=count, head=head, first_bad_seq=seq, reason=reason)

    def export(self, dest: Path) -> VerifyResult:
        """Copy the log to `dest` (JSONL) and return the verify result of what was exported."""
        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            shutil.copyfile(self.path, dest)
        return AuditLog(dest, self.clock).verify()
