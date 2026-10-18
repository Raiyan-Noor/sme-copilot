"""PII tokenization of phone numbers, national/tax IDs and account numbers.

Protects invariants 2 and 4 and keeps PII out of the audit log and any anchored data (invariants 7, 9):
- Raw values live only in the tenant's pii_vault table. Everything else (transactions, logs, planner context)
  sees tokens such as `acct_kqzvmtrpbwha`.
- Tokens are a keyed HMAC-SHA256 of the normalized value, so the same number always maps to the same token within
  a tenant (joins and payee history still work), but tokens cannot be brute-forced back from the small phone/ID
  number space without the tenant key.
- Tokens contain only lowercase letters and '_', so a token in LLM output never trips the Numeric Firewall's digit
  check and never smuggles digits.
- Free-text scrubbing over-tokenizes on purpose: any unlabelled run of 8+ digits is treated as an account number.
  Losing a long reference number is acceptable; leaking an account number is not.
- reveal() is for the owner-facing UI and the executor only; never pass its output to the planner.
"""

import hashlib
import hmac
import re
import sqlite3
from datetime import date
from enum import StrEnum

from app.ledger.schema import get_meta

TOKEN_LETTERS = 12  # 26**12 ~ 2**56 per kind per tenant
TOKEN = re.compile(r"(?:tel|nid|acct)_[a-z]{%d}" % TOKEN_LETTERS)


class PiiKind(StrEnum):
    PHONE = "tel"
    NATIONAL_ID = "nid"
    ACCOUNT = "acct"


# A number body: a digit, then more digits each optionally preceded by one space or hyphen.
_BODY = r"\d(?:[\s\-]?\d){%d,%d}"

_LABELLED: list[tuple[PiiKind, re.Pattern[str]]] = [
    (
        PiiKind.NATIONAL_ID,
        re.compile(
            r"(?i)\b(?:nid|national\s*id|id\s*(?:no\.?|number|\#)|ssn|tax\s*id|tin|passport(?:\s*no\.?)?)"
            r"\s*[:#\-]?\s*([A-Za-z]{0,2}" + _BODY % (4, 19) + r")"
        ),
    ),
    (
        PiiKind.ACCOUNT,
        re.compile(
            r"(?i)(?<![\w/])(?:a/c|acct|account|acc|iban|card)\.?\s*(?:no\.?|number|\#)?\s*[:#\-]?\s*"
            r"([A-Za-z]{0,2}" + _BODY % (5, 33) + r")"
        ),
    ),
    (
        PiiKind.PHONE,
        re.compile(
            r"(?i)\b(?:tel|phone|ph|mob(?:ile)?|cell|whatsapp|wallet)\.?\s*(?:no\.?|number|\#)?\s*[:#\-]?\s*"
            r"(\+?\d(?:[\s\-().]?\d){6,14})"
        ),
    ),
]

_IBAN = re.compile(r"\b[A-Z]{2}\d{2}(?:\s?[A-Z0-9]{4}){2,7}(?:\s?[A-Z0-9]{1,4})?\b")
_INTL_PHONE = re.compile(r"(?<![\w+])\+\d(?:[\s\-().]?\d){6,14}(?!\d)")
# Not inside a word, a path, a decimal or a letter-prefixed reference such as INV-20261018-0042.
_LONG_DIGITS = re.compile(r"(?<![\w/])(?<![A-Za-z]-)(?<!\d\.)" + _BODY % (7, 18) + r"(?![\w/]|\.\d)")


def normalize(kind: PiiKind, raw: str) -> str:
    """Canonical form, so formatting differences ('017-1234 5678' vs '01712345678') give the same token."""
    if kind is PiiKind.PHONE:
        s = raw.strip()
        return ("+" if s.startswith("+") else "") + "".join(c for c in s if c.isascii() and c.isdigit())
    return "".join(c for c in raw.upper() if c.isascii() and c.isalnum())


def _looks_like_date(digits: str) -> bool:
    """An 8-digit run that parses as YYYYMMDD or DDMMYYYY is a date, not an account."""
    if len(digits) != 8:
        return False
    for y, m, d in ((digits[:4], digits[4:6], digits[6:]), (digits[4:], digits[2:4], digits[:2])):
        try:
            date(int(y), int(m), int(d))
            return True
        except ValueError:
            continue
    return False


class Tokenizer:
    """Tokenizes PII for one tenant. Writes to pii_vault on the given connection; the caller commits."""

    def __init__(self, conn: sqlite3.Connection):
        key_hex = get_meta(conn, "pii_key")
        if not key_hex:
            raise ValueError("tenant has no pii_key")
        self._conn = conn
        self._key = bytes.fromhex(key_hex)

    def token(self, kind: PiiKind, raw: str) -> str:
        """Token for a known-PII value (e.g. a dedicated account-number column). Records it in the vault."""
        value = normalize(kind, raw)
        if not any(c.isdigit() for c in value):
            raise ValueError(f"{kind.name.lower()} has no digits")
        digest = int.from_bytes(hmac.new(self._key, f"{kind}:{value}".encode(), hashlib.sha256).digest(), "big")
        letters = []
        for _ in range(TOKEN_LETTERS):
            digest, r = divmod(digest, 26)
            letters.append(chr(ord("a") + r))
        token = f"{kind}_{''.join(letters)}"
        self._conn.execute(
            "INSERT OR IGNORE INTO pii_vault (token, kind, value) VALUES (?, ?, ?)", (token, str(kind), value)
        )
        stored = self._conn.execute("SELECT value FROM pii_vault WHERE token = ?", (token,)).fetchone()
        if stored["value"] != value:  # 2**-56 per pair; fail loudly rather than merge two people's numbers
            raise RuntimeError("PII token collision")
        return token

    def scrub(self, text: str) -> str:
        """Replace phone numbers, IDs and account numbers in free text with tokens."""
        for kind, pattern in _LABELLED:
            text = pattern.sub(lambda m, k=kind: self._replace_group(m, k), text)
        text = _IBAN.sub(self._replace_iban, text)
        text = _INTL_PHONE.sub(lambda m: self.token(PiiKind.PHONE, m.group(0)), text)
        return _LONG_DIGITS.sub(self._replace_long_digits, text)

    def _replace_group(self, m: re.Match[str], kind: PiiKind) -> str:
        start = m.start(1) - m.start(0)
        return m.group(0)[:start] + self.token(kind, m.group(1))

    def _replace_iban(self, m: re.Match[str]) -> str:
        compact = normalize(PiiKind.ACCOUNT, m.group(0))
        if len(compact) < 15 or sum(c.isdigit() for c in compact) < 10:
            return m.group(0)
        return self.token(PiiKind.ACCOUNT, m.group(0))

    def _replace_long_digits(self, m: re.Match[str]) -> str:
        digits = "".join(c for c in m.group(0) if c.isdigit())
        if _looks_like_date(digits):
            return m.group(0)
        # A 10-11 digit number with a trunk '0' prefix is the common local mobile format; the rest are accounts.
        kind = PiiKind.PHONE if digits.startswith("0") and len(digits) in (10, 11) else PiiKind.ACCOUNT
        return self.token(kind, m.group(0))


def reveal(conn: sqlite3.Connection, token: str) -> str | None:
    """Raw value for a token. Owner UI and executor only; never the planner, the audit log or an anchor."""
    row = conn.execute("SELECT value FROM pii_vault WHERE token = ?", (token,)).fetchone()
    return row["value"] if row else None
