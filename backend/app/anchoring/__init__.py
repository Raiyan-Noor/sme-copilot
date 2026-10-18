"""On-chain anchoring of audit hashes (invariant 9).

Publishes only a Merkle root of hashes (audit-log head, newly signed mandates, exported Passports) in a 0-value
self-transaction on an allow-listed EVM testnet (Sepolia 11155111, Base Sepolia 84532). Never business data,
names, amounts or PII. Never blocks core flows: on RPC failure, queue, retry with backoff and log.

- merkle.py: index-based SHA-256 tree, proofs, odd-leaf handling (documented there)
- chain.py: web3.py testnet access behind the record/replay cache (namespace `rpc`)
- store.py: the `anchors` record, one row per batch
- service.py: batching, triggers, background worker, on-chain verification
"""

import re
from pathlib import Path

from app.anchoring.chain import CachedChain, Chain, ChainError, Web3Chain
from app.anchoring.service import AnchorService
from app.anchoring.store import AnchorStore
from app.audit import AuditLog
from app.config import Settings
from app.gateway.policy import load_policy
from app.llm.cache import RequestCache

__all__ = ["AnchorService", "build_chain", "create_service"]

_KEY = re.compile(r"^(0x)?[0-9a-fA-F]{64}$")


def anchor_mode(settings: Settings) -> str:
    return settings.anchor_replay or settings.llm_replay


def build_chain(settings: Settings) -> tuple[Chain | None, str | None]:
    """The chain from settings, and why sending is unavailable (None if it is available).

    Replay mode never sends; it can still verify anchors whose responses were recorded. Record and off mode send
    only with a real RPC URL and a 32-byte throwaway key. The key stays inside Web3Chain.
    """
    mode = anchor_mode(settings)
    cache = RequestCache(settings.anchor_replay_dir or settings.llm_replay_dir, mode)
    if mode == "replay":
        return CachedChain(cache, settings.anchor_chain_id), "replay mode: verifies recorded anchors, sends nothing"
    rpc = settings.anchor_rpc_url.strip()
    key = settings.anchor_private_key.get_secret_value().strip()
    if not rpc.startswith(("http://", "https://")) or ".invalid" in rpc or not _KEY.match(key):
        return None, "ANCHOR_RPC_URL and ANCHOR_PRIVATE_KEY are not set"
    try:
        live = Web3Chain(rpc, key, settings.anchor_chain_id)
    except (ValueError, ChainError) as exc:
        return None, f"anchor chain not usable ({exc.__class__.__name__})"
    return CachedChain(cache, settings.anchor_chain_id, live), None


def store_path(data_dir: Path) -> Path:
    """Outside the tenant namespace: every `*.sqlite` directly in data_dir is a business."""
    return Path(data_dir) / "_anchoring" / "anchors.sqlite"


def create_service(settings: Settings, audit: AuditLog, data_dir: Path, chain: Chain | None = None) -> AnchorService:
    """The anchoring service for this app, subscribed to `audit`. `chain` overrides settings (tests)."""
    reason = None
    if chain is None:
        chain, reason = build_chain(settings)
    service = AnchorService(
        audit, AnchorStore(store_path(data_dir)), chain, policy=load_policy(),
        chain_id=settings.anchor_chain_id, explorer_url=settings.anchor_explorer_url,
        batch_size=settings.anchor_batch_size, auto=settings.anchor_auto, background=settings.anchor_background,
        unavailable_reason=reason)
    audit.subscribe(service.on_entry)
    return service
