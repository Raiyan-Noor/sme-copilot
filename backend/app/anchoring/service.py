"""Anchoring service: cut batches, publish their roots in the background, verify against the chain (invariant 9).

The `anchor` system tool (policy.yaml `system_tools.anchor`: T1, caller system, testnet only, rate-capped, never
moves value). It is not in the planner's registry and the gateway refuses it as a proposal; only this service and
the "Anchor now" route call it.

Batches. A batch covers the audit entries since the previous batch's head: its leaves are the current head hash,
every `gateway.mandate_stored` record hash and every `passport.exported` hash in that range. Only hashes are
anchored. Each batch is logged when cut (`anchor.batch_created`) and when confirmed (`anchor.confirmed`); those
entries are themselves covered by the next batch's head.

Triggers: every `ANCHOR_BATCH_SIZE` audit entries (anchoring's own `anchor.*` entries do not count, so anchoring
cannot feed itself), at the end of each demo scenario (clock fast-forward, an owner signature, a Passport export) and
on demand. Automatic triggers run only when a chain that can send is configured.

Never blocking core flows: a trigger only cuts the batch (a local read and an insert) and wakes a worker thread. The
worker sends; on RPC failure the batch stays queued, the failure is logged without RPC details, and it retries with
exponential backoff. While a batch is queued, new triggers do not cut another: the next batch after it picks up
everything in between. Sends are rate-capped from policy.yaml; a capped batch waits for the window, it is not lost.

Verification recomputes everything locally (entry hashes from the log body, mandate and Passport hashes from their
documents) and compares the resulting root with the `data` of the transaction fetched from the chain. An insider who
rewrites the log and recomputes every hash passes the local chain check but not this one.

Time: the rate cap and backoff use `time.monotonic()` (elapsed seconds, not business time); batch dates come from
the simulated clock and anchoring times from the block.
"""

import threading
import time
from collections import deque
from collections.abc import Callable
from typing import Literal

from pydantic import BaseModel

from app.anchoring.chain import Chain, ChainError, ChainPending, ensure_testnet
from app.anchoring.merkle import LeafKind, ProofStep, build, leaf_hash, root_from_proof
from app.anchoring.store import AnchorBatch, AnchorStore, Leaf
from app.audit import AuditEntry, AuditLog
from app.audit.log import entry_hash
from app.gateway.policy import Policy

CHAIN_NAMES = {11155111: "Sepolia", 84532: "Base Sepolia"}
VERIFY_MAX_BATCHES = 20

# Audit kinds whose hash becomes a leaf, and the field holding it.
_LEAF_SOURCES: dict[str, tuple[LeafKind, str]] = {
    "gateway.mandate_stored": ("mandate", "record_hash"),
    "passport.exported": ("passport", "sha256"),
    "skill.uploaded": ("skill", "sha256"),
}


class AnchorBatchView(AnchorBatch):
    chain_name: str
    explorer_url: str | None


class AnchorStatus(BaseModel):
    configured: bool  # a chain that can send is set up
    reason: str | None  # why not, if not
    chain_id: int
    chain_name: str
    explorer_base_url: str
    batch_size: int
    auto: bool
    entries_since_last_batch: int
    queued: int
    batches: list[AnchorBatchView]  # newest first


class AnchorRequestResult(BaseModel):
    status: Literal["queued", "confirmed", "already_queued", "up_to_date", "not_configured", "auto_off"]
    reason: str | None = None
    batch: AnchorBatchView | None = None


class OnchainCheck(BaseModel):
    """One batch checked against the chain. `match` only if the transaction is a confirmed 0-value self-transaction
    on the allow-listed chain whose data equals the root recomputed here."""

    status: Literal["match", "mismatch", "unavailable", "pending"]
    rule: str | None  # the first check that failed, e.g. audit_head_mismatch, onchain_root_mismatch
    reason: str | None
    batch_id: str
    head_seq: int
    anchored_root: str
    recomputed_root: str | None
    onchain_root: str | None
    tx_hash: str | None
    chain_id: int
    block_number: int | None
    block_timestamp: int | None
    explorer_url: str | None


class LogAnchorCheck(BaseModel):
    """The audit log against every confirmed anchor (most recent first, up to VERIFY_MAX_BATCHES).
    `ok` is None when there is nothing on chain to compare with."""

    ok: bool | None
    batches: list[OnchainCheck]


class LeafCheck(BaseModel):
    status: Literal["match", "mismatch", "not_anchored", "queued", "unavailable"]
    reason: str | None
    kind: LeafKind
    hash: str  # recomputed now from the document
    recorded_hash: str | None  # what the server recorded when it was signed or exported
    batch_id: str | None = None
    leaf_hash: str | None = None
    proof: list[ProofStep] = []
    onchain: OnchainCheck | None = None


class AnchorService:
    def __init__(self, audit: AuditLog, store: AnchorStore, chain: Chain | None, *, policy: Policy, chain_id: int,
                 explorer_url: str, batch_size: int, auto: bool = True, background: bool = True,
                 unavailable_reason: str | None = None, monotonic: Callable[[], float] = time.monotonic,
                 backoff_base_s: float = 5.0, backoff_max_s: float = 300.0):
        self.audit = audit
        self.store = store
        self.chain_id = chain_id
        self.explorer_url = explorer_url.rstrip("/")
        self.batch_size = batch_size
        self.auto = auto
        self.background = background
        self._mono = monotonic
        self._backoff = (backoff_base_s, backoff_max_s)
        self.chain, self.reason = self._check_policy(policy, chain, unavailable_reason)
        tool = policy.system_tools["anchor"]
        self._rate_max = int(tool["rate_cap"]["max"])
        self._rate_window_s = 60.0 * int(tool["rate_cap"]["window_minutes"])
        self._sends: deque[float] = deque()
        self._next_attempt: dict[str, float] = {}
        self._rate_logged: set[str] = set()
        self._lock = threading.RLock()
        self._process_lock = threading.Lock()
        self._wake = threading.Event()
        self._thread: threading.Thread | None = None
        self._since = self._count_since_last()

    def _check_policy(self, policy: Policy, chain: Chain | None, reason: str | None) -> tuple[Chain | None, str | None]:
        """The anchor tool must be registered as a testnet-only, value-free system tool for this chain ID."""
        tool = policy.system_tools.get("anchor")
        if not tool or tool.get("caller") != "system" or tool.get("tier") != "T1" or tool.get("moves_value") \
                or not tool.get("testnet_only"):
            raise ValueError("policy.yaml must register `anchor` as a T1, system-only, testnet-only tool")
        ensure_testnet(self.chain_id)
        if self.chain_id not in tool.get("allowed_chain_ids", []):
            return None, f"chain {self.chain_id} is not allowed by policy.yaml"
        if chain is not None and chain.chain_id != self.chain_id:
            return None, "configured chain does not match ANCHOR_CHAIN_ID"
        return chain, reason

    # Status
    @property
    def configured(self) -> bool:
        return self.chain is not None and self.chain.can_send

    def explorer(self, tx_hash: str | None) -> str | None:
        return f"{self.explorer_url}/tx/{tx_hash}" if tx_hash and self.explorer_url else None

    def view(self, batch: AnchorBatch) -> AnchorBatchView:
        return AnchorBatchView(**batch.model_dump(), chain_name=CHAIN_NAMES.get(batch.chain_id, str(batch.chain_id)),
                               explorer_url=self.explorer(batch.tx_hash))

    def status(self) -> AnchorStatus:
        batches = self.store.all()
        return AnchorStatus(
            configured=self.configured, reason=None if self.configured else self._why_not(),
            chain_id=self.chain_id, chain_name=CHAIN_NAMES.get(self.chain_id, str(self.chain_id)),
            explorer_base_url=self.explorer_url, batch_size=self.batch_size, auto=self.auto,
            entries_since_last_batch=self._since, queued=sum(b.status != "confirmed" for b in batches),
            batches=[self.view(b) for b in reversed(batches)])

    def _why_not(self) -> str:
        return self.reason or "no testnet RPC and anchor key configured"

    # Triggers
    def _count_since_last(self) -> int:
        last = self.store.latest()
        after = last.head_seq if last else -1
        return sum(1 for e in self.audit.entries() if e.seq > after and not e.kind.startswith("anchor."))

    def on_entry(self, entry: AuditEntry) -> None:
        """Audit subscriber: count entries and cut a batch every `batch_size` of them."""
        if entry.kind.startswith("anchor."):
            return
        with self._lock:
            self._since += 1
            due = self._since >= self.batch_size
        if due:
            self.request("batch_size")

    def request(self, trigger: str, *, manual: bool = False) -> AnchorRequestResult:
        """Cut a batch (if there is anything new) and hand it to the worker. Returns at once in background mode."""
        if not self.configured:
            if manual:
                self.audit.append("anchor.refused", {"tool": "anchor", "tier": "T1", "caller": "system",
                                                     "trigger": trigger, "reason": self._why_not()})
            return AnchorRequestResult(status="not_configured", reason=self._why_not())
        if not manual and not self.auto:
            return AnchorRequestResult(status="auto_off")
        with self._lock:
            pending = self.store.unconfirmed()
            if pending:
                if manual:
                    self._next_attempt.clear()  # the owner asked: retry now rather than wait out the backoff
                result = AnchorRequestResult(status="already_queued", batch=self.view(pending[0]))
                batch_id = None
            else:
                batch = self._cut(trigger)
                if batch is None:
                    last = self.store.latest()
                    return AnchorRequestResult(status="up_to_date", batch=self.view(last) if last else None)
                batch_id = batch.batch_id
        self._kick()
        if batch_id is None:
            return result
        batch = self.store.get(batch_id)
        return AnchorRequestResult(status="confirmed" if batch.status == "confirmed" else "queued",
                                   batch=self.view(batch))

    def _cut(self, trigger: str) -> AnchorBatch | None:
        last = self.store.latest()
        after = last.head_seq if last else -1
        entries = [e for e in self.audit.entries() if e.seq > after]
        if not entries:
            return None
        head = entries[-1]
        found: list[tuple[LeafKind, str, str]] = []
        seen: set[tuple[str, str]] = set()
        for e in entries:
            source = _LEAF_SOURCES.get(e.kind)
            if source and isinstance(e.data.get(source[1]), str) and (source[0], e.data[source[1]]) not in seen:
                seen.add((source[0], e.data[source[1]]))
                ref = f"mandate {e.data.get('mandate_id')}" if source[0] == "mandate" else \
                    f"passport {e.data.get('business_id')}"
                found.append((source[0], e.data[source[1]], f"{ref} (audit #{e.seq})"))
        if not found and all(e.kind.startswith("anchor.") for e in entries):
            return None  # only anchoring's own records since the last batch; they ride along with the next one
        raw = [("audit_head", head.hash, f"audit #{head.seq}"), *found]
        hashes = [leaf_hash(kind, value) for kind, value, _ in raw]
        root, proofs = build(hashes)
        batch = AnchorBatch(
            batch_id=self.store.next_batch_id(), trigger=trigger, merkle_root=root,
            leaves=[Leaf(kind=k, hash=v, ref=r, leaf_hash=h, proof=p) for (k, v, r), h, p in zip(raw, hashes, proofs)],
            head_seq=head.seq, head_hash=head.hash, created_on=self.audit.clock.today(), status="queued", attempts=0,
            last_error=None, tx_hash=None, chain_id=self.chain_id, from_address=None, block_number=None,
            block_timestamp=None)
        self.store.add(batch)
        self._since = 0
        self.audit.append("anchor.batch_created", {
            "tool": "anchor", "tier": "T1", "caller": "system", "trigger": trigger, "batch_id": batch.batch_id,
            "merkle_root": root, "head_seq": head.seq, "head_hash": head.hash, "chain_id": self.chain_id,
            "leaves": {k: sum(x[0] == k for x in raw) for k in ("audit_head", "mandate", "passport", "skill")},
        })
        return batch

    # Worker
    def _kick(self) -> None:
        if not self.background:
            self.process_once()
            return
        with self._lock:
            if self._thread is None or not self._thread.is_alive():
                self._thread = threading.Thread(target=self._run, name="anchor-worker", daemon=True)
                self._thread.start()
        self._wake.set()

    def _run(self) -> None:
        while True:
            self._wake.clear()
            try:
                self.process_once()
            except Exception as exc:  # the worker must survive anything; the batch stays queued
                self.audit.append("anchor.failed", {"tool": "anchor", "error": exc.__class__.__name__})
            pending = [b.batch_id for b in self.store.unconfirmed()]
            if not pending:
                self._wake.wait()
                continue
            wait = min(self._next_attempt.get(b, 0.0) for b in pending) - self._mono()
            self._wake.wait(timeout=max(wait, 1.0))

    def process_once(self) -> None:
        """Try every queued batch whose backoff has elapsed, once, oldest first."""
        with self._process_lock:
            for batch in self.store.unconfirmed():
                if self._mono() < self._next_attempt.get(batch.batch_id, 0.0):
                    continue
                if batch.status == "sent":
                    self._confirm_sent(batch)
                    continue
                if not self._rate_ok(batch):
                    continue
                self._sends.append(self._mono())
                try:
                    tx = self.chain.send_anchor(batch.merkle_root)
                except ChainPending as pending:
                    self.store.mark_sent(batch.batch_id, pending.tx_hash)
                    self._fail(batch, pending, sent=pending.tx_hash)
                    continue
                except ChainError as exc:
                    self._fail(batch, exc)
                    continue
                self._confirmed(batch, tx.tx_hash, tx.chain_id, tx.from_address, tx.block_number,
                                tx.block_timestamp)

    def _rate_ok(self, batch: AnchorBatch) -> bool:
        now = self._mono()
        while self._sends and now - self._sends[0] >= self._rate_window_s:
            self._sends.popleft()
        if len(self._sends) < self._rate_max:
            return True
        self._next_attempt[batch.batch_id] = self._sends[0] + self._rate_window_s
        if batch.batch_id not in self._rate_logged:
            self._rate_logged.add(batch.batch_id)
            self.audit.append("anchor.rate_limited", {"tool": "anchor", "batch_id": batch.batch_id,
                                                      "rule": "rate_cap", "max": self._rate_max,
                                                      "window_minutes": int(self._rate_window_s // 60)})
        return False

    def _confirm_sent(self, batch: AnchorBatch) -> None:
        try:
            tx = self.chain.get_tx(batch.tx_hash)
        except ChainError as exc:
            self._fail(batch, exc, sent=batch.tx_hash)
            return
        if tx.block_number is None:
            self._fail(batch, ChainError("anchor transaction not yet mined"), sent=batch.tx_hash)
        elif tx.data_hex != batch.merkle_root or tx.succeeded is False:
            # Never expected for our own tx; never claim an anchor it does not prove.
            self._fail(batch, ChainError("sent transaction does not carry this root"))
        else:
            self._confirmed(batch, tx.tx_hash, tx.chain_id, tx.from_address, tx.block_number, tx.block_timestamp)

    def _fail(self, batch: AnchorBatch, exc: ChainError, sent: str | None = None) -> None:
        self.store.mark_attempt(batch.batch_id, str(exc))
        attempts = batch.attempts + 1
        base, cap = self._backoff
        delay = min(base * 2 ** (attempts - 1), cap)
        self._next_attempt[batch.batch_id] = self._mono() + delay
        self.audit.append("anchor.failed", {"tool": "anchor", "batch_id": batch.batch_id, "attempt": attempts,
                                            "error": str(exc), "tx_hash": sent, "retry_in_s": int(delay)})

    def _confirmed(self, batch: AnchorBatch, tx_hash: str, chain_id: int, from_address: str, block_number: int,
                   block_timestamp: int) -> None:
        if chain_id != self.chain_id:
            self._fail(batch, ChainError(f"transaction landed on chain {chain_id}, expected {self.chain_id}"))
            return
        self.store.mark_confirmed(batch.batch_id, tx_hash, from_address, block_number, block_timestamp)
        self._next_attempt.pop(batch.batch_id, None)
        self.audit.append("anchor.confirmed", {
            "tool": "anchor", "tier": "T1", "caller": "system", "batch_id": batch.batch_id,
            "merkle_root": batch.merkle_root, "tx_hash": tx_hash, "chain_id": chain_id, "block_number": block_number,
            "block_timestamp": block_timestamp, "explorer_url": self.explorer(tx_hash),
        })

    # Verification
    def check_onchain(self, batch: AnchorBatch, recomputed_root: str | None,
                      local_problem: tuple[str, str] | None = None) -> OnchainCheck:
        """Fetch the batch's transaction and compare its data with `recomputed_root`. `local_problem` is a
        (rule, reason) found while recomputing, reported ahead of the generic root mismatch."""
        def result(status, rule, why, onchain_root=None, tx=None):
            return OnchainCheck(
                status=status, rule=rule, reason=why, batch_id=batch.batch_id, head_seq=batch.head_seq,
                anchored_root=batch.merkle_root, recomputed_root=recomputed_root, onchain_root=onchain_root,
                tx_hash=batch.tx_hash, chain_id=batch.chain_id,
                block_number=tx.block_number if tx else batch.block_number,
                block_timestamp=tx.block_timestamp if tx else batch.block_timestamp,
                explorer_url=self.explorer(batch.tx_hash))

        if batch.status != "confirmed" or not batch.tx_hash:
            return result("pending", None, "not yet anchored on chain")
        if self.chain is None:
            return result("unavailable", None, self._why_not())
        try:
            ensure_testnet(batch.chain_id)
            tx = self.chain.get_tx(batch.tx_hash)
        except ChainError as exc:
            return result("unavailable", None, str(exc))
        problems: list[tuple[str, str]] = []
        if tx.chain_id != batch.chain_id or tx.chain_id != self.chain_id:
            problems.append(("wrong_chain", f"transaction is on chain {tx.chain_id}"))
        if tx.block_number is None or tx.succeeded is False:
            problems.append(("not_confirmed", "transaction is not confirmed"))
        if (tx.to_address or "").lower() != tx.from_address.lower() or tx.value_wei != 0:
            problems.append(("not_self_transaction", "transaction is not a 0-value self-transaction"))
        if batch.from_address and tx.from_address.lower() != batch.from_address.lower():
            problems.append(("different_sender", "transaction was sent from a different address"))
        if recomputed_root is None or tx.data_hex != recomputed_root:
            problems.append(local_problem or ("onchain_root_mismatch",
                                              "the root recomputed here differs from the root on chain"))
        if problems:
            return result("mismatch", problems[0][0], "; ".join(p[1] for p in problems), tx.data_hex, tx)
        return result("match", None, None, tx.data_hex, tx)

    def verify_log(self) -> LogAnchorCheck:
        """Recompute every entry hash from the log body and check each confirmed batch's root against the chain."""
        recomputed: dict[int, str] = {}
        for e in self.audit.entries():
            recomputed.setdefault(e.seq, entry_hash(e.body()))
        confirmed = [b for b in self.store.all() if b.status == "confirmed"][-VERIFY_MAX_BATCHES:]
        checks = []
        for batch in reversed(confirmed):
            local = recomputed.get(batch.head_seq)
            if local is None:
                checks.append(self.check_onchain(batch, None, (
                    "anchored_entry_missing", f"audit entry #{batch.head_seq} is missing")))
                continue
            values = [(leaf.kind, local if leaf.kind == "audit_head" else leaf.hash) for leaf in batch.leaves]
            root, _ = build([leaf_hash(k, v) for k, v in values])
            why = None if local == batch.head_hash else (
                "audit_head_mismatch", f"audit entry #{batch.head_seq} differs from the anchored head")
            checks.append(self.check_onchain(batch, root, why))
        if checks:
            self.audit.append("anchor.log_verified", {
                "tool": "anchor", "caller": "system", "batches": len(checks),
                "results": {s: sum(c.status == s for c in checks) for s in ("match", "mismatch", "unavailable")}})
        decided = [c for c in checks if c.status in ("match", "mismatch")]
        ok = None if not decided else all(c.status == "match" for c in decided)
        return LogAnchorCheck(ok=ok, batches=checks)

    def verify_leaf(self, kind: LeafKind, recomputed_hash: str, recorded_hash: str | None = None) -> LeafCheck:
        """Is this hash (recomputed from the document now) in an anchored batch whose root is on chain?"""
        base = {"kind": kind, "hash": recomputed_hash, "recorded_hash": recorded_hash}
        found = self.store.find(kind, recomputed_hash)
        if not found:
            if recorded_hash and recorded_hash != recomputed_hash and self.store.find(kind, recorded_hash):
                check = LeafCheck(status="mismatch", reason="the document changed after it was anchored", **base)
            else:
                check = LeafCheck(status="not_anchored", reason="not in any anchored batch yet", **base)
            return self._log_leaf(check)
        confirmed = [(b, leaf) for b, leaf in found if b.status == "confirmed"]
        batch, leaf = (confirmed or found)[-1]
        mine = leaf_hash(kind, recomputed_hash)
        root = root_from_proof(mine, leaf.proof)
        common = {**base, "batch_id": batch.batch_id, "leaf_hash": mine, "proof": leaf.proof}
        if not confirmed:
            return self._log_leaf(LeafCheck(status="queued", reason="batch not yet confirmed on chain", **common))
        onchain = self.check_onchain(batch, root)
        status = {"match": "match", "mismatch": "mismatch"}.get(onchain.status, "unavailable")
        return self._log_leaf(LeafCheck(status=status, reason=onchain.reason, onchain=onchain, **common))

    def _log_leaf(self, check: LeafCheck) -> LeafCheck:
        self.audit.append("anchor.leaf_verified", {"tool": "anchor", "caller": "system", "kind": check.kind,
                                                   "hash": check.hash, "status": check.status,
                                                   "batch_id": check.batch_id})
        return check
