"""Planner loop, tool registry (read/compute tools + propose_action) and conversation state.

Invariant 1: the planner proposes; it never executes. Every action goes through propose_action -> gateway.
Invariant 2: the planner sees only schema-validated fields from quarantine, never raw untrusted text.
Invariant 5: no Tier 4 tool is ever registered here.

- planner.py: the loop, the Numeric Firewall gate on every reply (one re-prompt, then template fallback).
- tools.py: Tier 1 read/compute tools; numbers leave them only as {fact:<id>} placeholders.
- actions.py: propose_action; amounts come from facts, provenance is decided in code, the gateway decides.
- context.py: conversation state and the per-turn FactStore; events.py: what the UI receives.
"""
