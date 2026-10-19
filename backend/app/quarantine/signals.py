"""Deterministic text signals over quarantined content: instruction-like text, urgency and secrecy.

Defence in depth for invariant 2: the extractor model is asked to flag these too, but a model can miss them or be
talked out of it by the very text it is reading. These patterns run in code over the raw text (including hidden
PDF/HTML text) and are OR-ed with the model's flags. Each match is reported by pattern name only; the matched text
is never copied anywhere the planner can reach.
"""

import re
from dataclasses import dataclass

_I = re.I

INSTRUCTION_PATTERNS: dict[str, re.Pattern[str]] = {
    "ignore_instructions": re.compile(
        r"\b(ignore|disregard|forget|override)\b[^.\n]{0,40}\b(previous|prior|above|earlier|all|your|system)\b"
        r"[^.\n]{0,20}\b(instructions?|rules?|prompts?|guidelines?|polic(y|ies))", _I),
    "addressed_to_ai": re.compile(
        r"\b(note|message|instructions?)\s+(for|to)\s+(the\s+)?(ai|assistant|agent|bot|model|llm)\b"
        r"|\b(ai|llm)\s+(assistant|agent|model)\b|\bsystem\s+(note|prompt|message)\b"
        r"|\bassistant\s+(reading|processing)\b", _I),
    "claims_owner_authority": re.compile(
        r"\b(pre-?approved|already\s+approved|authori[sz]ed)\s+by\s+the\s+(owner|management|ceo)"
        r"|\b(owner'?s?|ceo'?s?)\s+authori[sz]ed\b|\bon\s+behalf\s+of\s+the\s+owner\b", _I),
    "approval_bypass": re.compile(
        r"\b(without|no\s+need\s+for|skip(ping)?)\b[^.\n]{0,30}\b(signature|approval|confirmation|verification)"
        r"|\bdo\s+not\s+ask\s+for\s+(confirmation|approval)|\bapprove\s+all\b", _I),
    "mandate_or_policy_change": re.compile(
        r"\b(raise|increase|change|lift|remove)\b[^.\n]{0,30}\b(mandate|cap|limit|polic(y|ies)|allow-?list)\b"
        r"|\badd\b[^.\n]{0,40}\b(known|trusted|approved)\s+payee", _I),
    "data_exfiltration": re.compile(
        r"\b(export|send|forward|upload|share)\b[^.\n]{0,60}\b(transactions|statements?|ledger|bank\s+data|"
        r"customer\s+list|records)\b[^.\n]{0,60}\bto\b", _I),
    "email_directive": re.compile(
        r"\b(please\s+)?(also\s+)?(e-?mail|send\s+(an?\s+)?(e-?mail|message)|forward\s+(this|it|the)|write\s+to)"
        r"\b[^.\n]{0,60}\b(to|cc|bcc)\b[^.\n]{0,60}(@|\b(all|every|each)\b[^.\n]{0,20}\b(customers?|suppliers?|"
        r"contacts?|clients?)\b)", _I),
    "concealment": re.compile(
        r"\bdo\s+not\s+(mention|tell|inform|show)\b|\bdon'?t\s+(mention|tell)\b|\bkeep\s+(this|it)\s+(secret|"
        r"quiet|confidential|between\s+us)", _I),
}

URGENCY_PATTERNS: dict[str, re.Pattern[str]] = {
    "urgent": re.compile(r"\burgent(ly)?\b|\basap\b|\bimmediately\b|\bright\s+away\b|\bfinal\s+notice\b", _I),
    "deadline_today": re.compile(
        r"\b(pay|send|transfer|wire|go)\b[^.\n]{0,40}\b(today|tonight|within\s+the\s+hour|before\s+\d{1,2}\s*"
        r"(:\d\d)?\s*(am|pm))\b|\bbefore\s+\d{1,2}\s*(:\d\d)?\s*(am|pm)\b", _I),
    "threat": re.compile(r"\b(avoid|or\s+(face|we\s+will))\b[^.\n]{0,30}\b(suspension|suspend|legal|penalt|"
                         r"cut\s*off|lose)\b|\bor\s+we\s+lose\b", _I),
}

SECRECY_PATTERNS: dict[str, re.Pattern[str]] = {
    "no_callback": re.compile(r"\b(don'?t|do\s+not)\s+call\b|\bcan'?t\s+(talk|pick\s+up)\b|\bno\s+calls?\b", _I),
    "secrecy": INSTRUCTION_PATTERNS["concealment"],
}


@dataclass(frozen=True)
class TextSignals:
    instruction_patterns: tuple[str, ...]
    urgency_patterns: tuple[str, ...]
    secrecy_patterns: tuple[str, ...]

    @property
    def instruction_like(self) -> bool:
        return bool(self.instruction_patterns)

    @property
    def urgency(self) -> bool:
        return bool(self.urgency_patterns or self.secrecy_patterns)


def _hits(patterns: dict[str, re.Pattern[str]], text: str) -> tuple[str, ...]:
    return tuple(name for name, p in patterns.items() if p.search(text))


def scan(*texts: str) -> TextSignals:
    joined = "\n".join(t for t in texts if t)
    return TextSignals(_hits(INSTRUCTION_PATTERNS, joined), _hits(URGENCY_PATTERNS, joined),
                       _hits(SECRECY_PATTERNS, joined))
