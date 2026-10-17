"""Finance engine: P&L, margins, buffer days, forecast, financing match and safe sizing, passport, leaks.

Every function is pure: (ledger snapshot, pack, clock) -> list[Fact]. Protects invariant 4 (Numeric Firewall):
numbers shown to the owner are computed here, never by the LLM.
"""
