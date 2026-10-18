"""What the business already knows: counterparties, their domains and bank accounts, and its payment history.

Built only from trusted sources: the business's own contact book (counterparties.json in its seed folder, the
synthetic stand-in for an accounting system's supplier and customer records) and its ledger. Never from email.

Bank accounts are compared as PII tokens (ledger/pii.py, the tenant's key), the same tokens the ledger stores in
`transactions.counterparty_ref`, so "has this business ever paid this account?" is a lookup on history.
"""

import json
import sqlite3
import statistics
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from app.ledger.pii import PiiKind, Tokenizer


@dataclass(frozen=True)
class Counterparty:
    id: str
    name: str
    kind: str  # supplier | payee | customer | staff | owner
    domains: frozenset[str] = frozenset()
    emails: frozenset[str] = frozenset()
    account_tokens: frozenset[str] = frozenset()
    account_last4: tuple[str, ...] = ()
    person_names: tuple[str, ...] = ()
    terms_days: int | None = None


@dataclass
class Directory:
    business_name: str
    own_domain: str
    owner_name: str
    owner_email: str
    counterparties: dict[str, Counterparty] = field(default_factory=dict)
    known_domains: frozenset[str] = frozenset()
    payments_by_token: dict[str, list[int]] = field(default_factory=dict)  # outgoing amounts, minor units
    category_by_counterparty: dict[str, str] = field(default_factory=dict)
    typical_payment_minor: int = 0  # median outgoing payment across the business

    def by_domain(self, domain: str) -> Counterparty | None:
        for cp in self.counterparties.values():
            if domain in cp.domains:
                return cp
        return None

    def by_account(self, token: str) -> Counterparty | None:
        for cp in self.counterparties.values():
            if token in cp.account_tokens:
                return cp
        return None

    def history_for(self, cp: Counterparty) -> list[int]:
        return [a for t in cp.account_tokens for a in self.payments_by_token.get(t, [])]


def _domain(email: str | None) -> str | None:
    return email.rsplit("@", 1)[1].lower() if email and "@" in email else None


def load_directory(conn: sqlite3.Connection, seed_folder: Path | None, business_name: str) -> Directory:
    tok = Tokenizer(conn)
    doc: dict = {}
    business: dict = {}
    if seed_folder and (seed_folder / "counterparties.json").is_file():
        doc = json.loads((seed_folder / "counterparties.json").read_text(encoding="utf-8"))
    if seed_folder and (seed_folder / "business.json").is_file():
        business = json.loads((seed_folder / "business.json").read_text(encoding="utf-8"))
    owner = doc.get("owner") or business.get("owner") or {}
    own_domain = (business.get("domain") or _domain(owner.get("email")) or "").lower()

    def accounts(*numbers: str | None) -> tuple[frozenset[str], tuple[str, ...]]:
        nums = [n for n in numbers if n]
        return frozenset(tok.token(PiiKind.ACCOUNT, n) for n in nums), tuple(n.replace(" ", "")[-4:] for n in nums)

    cps: dict[str, Counterparty] = {}
    for s in doc.get("suppliers", []):
        toks, last4 = accounts(*[a.get("account_number") for a in s.get("bank_accounts", [])])
        cps[s["id"]] = Counterparty(s["id"], s["name"], "supplier",
                                    frozenset(filter(None, [s.get("domain"), _domain(s.get("billing_email"))])),
                                    frozenset(filter(None, [s.get("billing_email")])), toks, last4,
                                    tuple(filter(None, [s.get("contact_name")])), s.get("terms_days"))
    for p in doc.get("payees", []):
        toks, last4 = accounts(p.get("account_number"))
        cps[p["id"]] = Counterparty(p["id"], p["name"], "payee", frozenset(filter(None, [p.get("email_domain")])),
                                    frozenset(), toks, last4)
    for c in doc.get("customers", []):
        cps[c["id"]] = Counterparty(c["id"], c["name"], "customer",
                                    frozenset(filter(None, [c.get("domain"), _domain(c.get("email"))])),
                                    frozenset(filter(None, [c.get("email")])), terms_days=c.get("terms_days"))
    for s in doc.get("staff", []):
        toks, last4 = accounts(s.get("bank_account"))
        cps[s["id"]] = Counterparty(s["id"], s["name"], "staff", frozenset({own_domain}) if own_domain else frozenset(),
                                    frozenset(filter(None, [s.get("email")])), toks, last4, (s["name"],))
    if owner.get("name"):
        cps["owner"] = Counterparty("owner", owner["name"], "owner", frozenset({own_domain}),
                                    frozenset(filter(None, [owner.get("email")])), person_names=(owner["name"],))
    tok_domains = set(doc.get("known_domains", [])) | {d for cp in cps.values() for d in cp.domains}

    payments: dict[str, list[int]] = defaultdict(list)
    outgoing: list[int] = []
    for row in conn.execute("SELECT counterparty_ref, amount_minor FROM transactions WHERE amount_minor < 0"):
        outgoing.append(-row["amount_minor"])
        if row["counterparty_ref"]:
            payments[row["counterparty_ref"]].append(-row["amount_minor"])
    categories: dict[str, str] = {}
    for row in conn.execute("SELECT counterparty_id, category FROM scheduled_items "
                            "WHERE counterparty_id IS NOT NULL ORDER BY due_date"):
        categories[row["counterparty_id"]] = row["category"]
    conn.commit()  # tokenizing known accounts may have added vault rows

    return Directory(
        business_name=business_name,
        own_domain=own_domain,
        owner_name=owner.get("name") or "",
        owner_email=(owner.get("email") or "").lower(),
        counterparties=cps,
        known_domains=frozenset(d.lower() for d in tok_domains if d),
        payments_by_token=dict(payments),
        category_by_counterparty=categories,
        typical_payment_minor=int(statistics.median(outgoing)) if outgoing else 0,
    )
