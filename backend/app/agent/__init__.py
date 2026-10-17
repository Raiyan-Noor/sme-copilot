"""Planner loop, tool registry (read/compute tools + propose_action) and conversation state.

Invariant 1: the planner proposes; it never executes. Every action goes through propose_action -> gateway.
Invariant 2: the planner sees only schema-validated fields from quarantine, never raw untrusted text.
Invariant 5: no Tier 4 tool is ever registered here.
"""
