"""Gateway: the only path from a proposed action to execution (invariant 1).

Checks every propose_action against policy.yaml and a valid Ed25519-signed mandate (invariant 6), escalates
untrusted-provenance arguments to Tier 3 (invariant 3), rejects replayed nonces and expired mandates, denies
unknown tools, and logs every decision (invariant 7).
"""

from app.gateway.engine import (
    ApprovalRequest,
    ArgValue,
    Decision,
    Gateway,
    MandateResult,
    ProposedAction,
)
from app.gateway.mandate import MandateRecord, SignedPayload, StandingTerms, args_hash, verify_signature
from app.gateway.policy import Policy, load_policy
from app.gateway.store import GatewayStore

__all__ = [
    "ApprovalRequest",
    "ArgValue",
    "Decision",
    "Gateway",
    "GatewayStore",
    "MandateRecord",
    "MandateResult",
    "Policy",
    "ProposedAction",
    "SignedPayload",
    "StandingTerms",
    "args_hash",
    "load_policy",
    "verify_signature",
]
