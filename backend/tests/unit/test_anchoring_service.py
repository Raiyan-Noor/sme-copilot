"""Anchoring service (invariant 9): batches, triggers, queue and backoff on RPC failure, rate cap, allow-list,
record/replay of the RPC, and the `anchor` tool's place in policy.yaml."""

from datetime import date
from pathlib import Path

import pytest

import app.agent
from app.agent.tools import READ_TOOLS
from app.anchoring import build_chain
from app.anchoring.chain import CachedChain, ChainError, ensure_testnet
from app.anchoring.merkle import leaf_hash, verify_proof
from app.anchoring.service import AnchorService
from app.anchoring.store import AnchorStore
from app.audit import AuditLog
from app.clock import FixedClock
from app.config import Settings
from app.gateway.policy import load_policy
from app.llm.cache import RequestCache
from tests.anchor_env import SEPOLIA, SimulatedChain, recording_chain
from tests.helpers import make_settings


class Ticker:
    def __init__(self):
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def service(tmp_path, chain, *, batch_size=1000, auto=True, ticker=None) -> AnchorService:
    log = AuditLog(tmp_path / "audit.jsonl", FixedClock(date(2026, 10, 18)))
    svc = AnchorService(log, AnchorStore(tmp_path / "anchors.sqlite"), chain, policy=load_policy(),
                        chain_id=SEPOLIA, explorer_url="https://sepolia.etherscan.io/", batch_size=batch_size,
                        auto=auto, background=False, monotonic=ticker or Ticker())
    log.subscribe(svc.on_entry)
    return svc


def kinds(svc: AnchorService) -> list[str]:
    return [e.kind for e in svc.audit.entries()]


def test_batch_holds_head_mandates_and_passports_with_proofs(tmp_path):
    chain = SimulatedChain()
    svc = service(tmp_path, chain)
    svc.audit.append("gateway.mandate_stored", {"mandate_id": 1, "record_hash": "a1" * 32})
    svc.audit.append("passport.exported", {"business_id": "maya-corner-store", "sha256": "b2" * 32})
    svc.audit.append("passport.exported", {"business_id": "maya-corner-store", "sha256": "b2" * 32})  # same file
    result = svc.request("manual", manual=True)
    assert result.status == "confirmed"
    batch = result.batch
    assert [(leaf.kind, leaf.hash) for leaf in batch.leaves] == [
        ("audit_head", svc.audit.entries()[2].hash), ("mandate", "a1" * 32), ("passport", "b2" * 32)]
    assert batch.head_seq == 2
    for leaf in batch.leaves:
        assert leaf.leaf_hash == leaf_hash(leaf.kind, leaf.hash)
        assert verify_proof(leaf.leaf_hash, leaf.proof, batch.merkle_root)
    assert chain.txs[batch.tx_hash].data_hex == batch.merkle_root
    assert batch.explorer_url == f"https://sepolia.etherscan.io/tx/{batch.tx_hash}"
    assert kinds(svc)[-2:] == ["anchor.batch_created", "anchor.confirmed"]
    created = svc.audit.entries()[-2].data
    assert created["tool"] == "anchor" and created["caller"] == "system" and created["tier"] == "T1"


def test_only_hashes_reach_the_chain(tmp_path):
    """Invariant 9: the transaction data is exactly the 32-byte root; no names, amounts or IDs."""
    chain = SimulatedChain()
    svc = service(tmp_path, chain)
    svc.audit.append("ledger.imported", {"business": "Maya's Corner Store", "amount_minor": 123456})
    batch = svc.request("manual", manual=True).batch
    tx = chain.txs[batch.tx_hash]
    assert len(bytes.fromhex(tx.data_hex)) == 32 and tx.value_wei == 0 and tx.to_address == tx.from_address


def test_anchor_entries_go_into_the_next_batch_but_never_trigger_one(tmp_path):
    svc = service(tmp_path, SimulatedChain())
    svc.audit.append("x.happened")
    first = svc.request("manual", manual=True).batch
    assert svc.request("manual", manual=True).status == "up_to_date"  # only anchor.* since: nothing to anchor
    svc.audit.append("x.happened")
    second = svc.request("manual", manual=True).batch
    assert second.head_seq > first.head_seq
    covered = [e.kind for e in svc.audit.entries() if first.head_seq < e.seq <= second.head_seq]
    assert "anchor.confirmed" in covered  # the first anchor's own record is inside the second batch


def test_every_batch_size_entries_cuts_a_batch(tmp_path):
    chain = SimulatedChain()
    svc = service(tmp_path, chain, batch_size=5)
    for i in range(12):
        svc.audit.append("x.happened", {"i": i})
    batches = svc.store.all()
    assert [b.head_seq for b in batches] == [4, 11]  # anchor.* entries in between are not counted
    assert all(b.trigger == "batch_size" and b.status == "confirmed" for b in batches)


def test_rpc_failure_queues_retries_with_backoff_and_logs(tmp_path):
    ticker = Ticker()
    chain = SimulatedChain(fail=2)
    svc = service(tmp_path, chain, ticker=ticker)
    svc.audit.append("x.happened")
    assert svc.request("manual", manual=True).status == "queued"
    failed = [e for e in svc.audit.entries() if e.kind == "anchor.failed"]
    assert failed[-1].data["attempt"] == 1 and failed[-1].data["retry_in_s"] == 5
    assert "http" not in failed[-1].data["error"]  # no RPC URL (it may carry an API key)

    svc.process_once()  # backoff not elapsed: no call
    assert chain.sends == 1
    ticker.now += 5
    svc.process_once()
    assert chain.sends == 2
    assert [e for e in svc.audit.entries() if e.kind == "anchor.failed"][-1].data["retry_in_s"] == 10
    # New activity while queued does not cut a second batch.
    svc.audit.append("y.happened")
    assert svc.request("scenario_end").status == "already_queued"
    ticker.now += 10
    svc.process_once()
    (batch,) = svc.store.all()
    assert batch.status == "confirmed" and batch.attempts == 2
    assert "anchor.confirmed" in kinds(svc)


def test_manual_anchor_retries_now_instead_of_waiting(tmp_path):
    chain = SimulatedChain(fail=1)
    svc = service(tmp_path, chain)
    svc.audit.append("x.happened")
    assert svc.request("manual", manual=True).status == "queued"
    assert svc.request("manual", manual=True).status == "already_queued"
    assert svc.store.all()[0].status == "confirmed"


def test_rate_cap_from_policy_holds_batches_until_the_window_passes(tmp_path):
    ticker = Ticker()
    chain = SimulatedChain()
    svc = service(tmp_path, chain, ticker=ticker)
    cap = load_policy().system_tools["anchor"]["rate_cap"]
    for _ in range(cap["max"]):
        svc.audit.append("x.happened")
        assert svc.request("manual", manual=True).status == "confirmed"
    svc.audit.append("x.happened")
    assert svc.request("manual", manual=True).status == "queued"
    assert chain.sends == cap["max"]
    limited = [e for e in svc.audit.entries() if e.kind == "anchor.rate_limited"]
    assert limited and limited[0].data["rule"] == "rate_cap"
    ticker.now += 60 * cap["window_minutes"]
    svc.process_once()
    assert svc.store.all()[-1].status == "confirmed"


def test_not_configured_refuses_manual_and_ignores_automatic(tmp_path):
    svc = service(tmp_path, None, batch_size=2)
    for _ in range(4):
        svc.audit.append("x.happened")
    assert svc.store.all() == []
    assert "anchor.refused" not in kinds(svc)
    result = svc.request("manual", manual=True)
    assert result.status == "not_configured"
    assert kinds(svc)[-1] == "anchor.refused"


def test_auto_off_still_allows_anchor_now(tmp_path):
    svc = service(tmp_path, SimulatedChain(), batch_size=1, auto=False)
    svc.audit.append("x.happened")
    assert svc.store.all() == []
    assert svc.request("scenario_end").status == "auto_off"
    assert svc.request("manual", manual=True).status == "confirmed"


# --- chain allow-list -----------------------------------------------------------------------------------------------

@pytest.mark.parametrize("chain_id", [1, 8453, 137, 10, 5])
def test_non_testnet_chain_ids_are_refused_everywhere(chain_id, tmp_path):
    with pytest.raises(ValueError):
        Settings(_env_file=None, anchor_chain_id=chain_id)
    with pytest.raises(ChainError):
        ensure_testnet(chain_id)
    with pytest.raises(ChainError):
        CachedChain(RequestCache(tmp_path, "replay"), chain_id)


def test_base_sepolia_is_allowed(tmp_path):
    settings = make_settings(anchor_chain_id=84532, anchor_replay_dir=tmp_path)
    chain, _ = build_chain(settings)
    assert chain.chain_id == 84532


def test_service_refuses_a_chain_that_does_not_match_its_chain_id(tmp_path):
    svc = service(tmp_path, SimulatedChain(chain_id=84532))
    assert not svc.configured and "does not match" in svc.status().reason


# --- record / replay ------------------------------------------------------------------------------------------------

def test_replay_mode_sends_nothing_and_needs_no_keys(tmp_path):
    settings = make_settings(anchor_replay_dir=tmp_path)
    chain, reason = build_chain(settings)
    assert chain is not None and not chain.can_send and "replay" in reason


def test_live_mode_without_rpc_or_key_is_not_configured(tmp_path):
    settings = make_settings(anchor_replay="off", anchor_rpc_url="https://sepolia.rpc.placeholder.invalid",
                             anchor_private_key="0xREPLACE_WITH_THROWAWAY_TESTNET_KEY")
    chain, reason = build_chain(settings)
    assert chain is None and "not set" in reason


def test_recorded_rpc_replays_offline(tmp_path):
    rpc = tmp_path / "rpc"
    svc = service(tmp_path, recording_chain(rpc))
    svc.audit.append("x.happened")
    batch = svc.request("manual", manual=True).batch
    assert svc.verify_log().ok is True  # record mode: read live, recorded

    replay = CachedChain(RequestCache(rpc, "replay"), SEPOLIA)
    assert not replay.can_send
    assert replay.get_tx(batch.tx_hash).data_hex == batch.merkle_root
    with pytest.raises(ChainError):
        replay.get_tx("0x" + "00" * 32)
    with pytest.raises(ChainError):
        replay.send_anchor("11" * 32)


# --- policy ---------------------------------------------------------------------------------------------------------

def test_anchor_is_a_t1_system_tool_that_the_planner_cannot_use():
    policy = load_policy()
    tool = policy.system_tools["anchor"]
    assert tool["tier"] == "T1" and tool["caller"] == "system" and tool["testnet_only"] is True
    assert tool["moves_value"] is False and sorted(tool["allowed_chain_ids"]) == [84532, 11155111]
    assert tool["rate_cap"]["max"] >= 1
    assert policy.tier_of("anchor") is None  # not proposable: the gateway denies it as a system tool
    assert not any("anchor" in t.name for t in READ_TOOLS)
    agent_dir = Path(app.agent.__file__).parent
    assert not any("app.anchoring" in p.read_text(encoding="utf-8") for p in agent_dir.glob("*.py"))
