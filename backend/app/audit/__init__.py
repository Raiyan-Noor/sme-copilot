"""Hash-chained JSONL audit log: append, verify, export (invariant 7).

Every tool call, fact computation, LLM call, gateway decision and execution is appended here. Nothing writes to
the log except audit.append().
"""
