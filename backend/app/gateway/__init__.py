"""Gateway: the only path from a proposed action to execution (invariant 1).

Checks every propose_action against policy.yaml and a valid Ed25519-signed mandate (invariant 6), escalates
untrusted-provenance arguments to Tier 3 (invariant 3), rejects replayed nonces and expired mandates, denies
unknown tools, and logs every decision (invariant 7).
"""
