"""Draft loan applications: what `submit_loan_application` (T3) sends, built in code from the financing match.

The draft is a canonical JSON document (audit.canonical). Its ID is derived from its SHA-256, so the draft ID in
the action's arguments commits to the exact document: the owner's Ed25519 signature covers the args hash, which
covers the draft ID, which covers every byte of the draft (invariants 1 and 6). The ID is letters only, so it
never puts a digit in front of the planner or trips the Numeric Firewall.

A draft can only be built for a product whose rules all pass, for an amount between the product minimum and the
repayment-safe amount (engine.financing). Anything else is refused with the rule that fired: the agent cannot
prepare an application the business cannot safely repay.
"""

from typing import Any

from app.audit.canonical import canonical_hash
from app.engine.catalog import Catalog
from app.engine.financing import FinancingMatch, installment
from app.engine.passport import Passport
from app.firewall.render import render
from app.firewall.store import FactStore

SCHEMA = "loan_application_draft/v1"
ID_PREFIX = "lad_"
ID_LETTERS = 24  # one letter per hex digit of the hash: 96 bits
_NIBBLE = "abcdefghijklmnop"


class DraftError(ValueError):
    """The draft was refused; `rule` says why."""

    def __init__(self, rule: str):
        self.rule = rule
        super().__init__(rule)


def draft_id_for(sha256: str) -> str:
    return ID_PREFIX + "".join(_NIBBLE[int(c, 16)] for c in sha256[:ID_LETTERS])


def build_draft(*, match: FinancingMatch, passport: Passport, passport_sha256: str, store: FactStore,
                catalog: Catalog, product_id: str, amount_minor: int) -> tuple[str, str, dict[str, Any]]:
    """(draft_id, sha256, document). Raises DraftError(rule) for an unknown, ineligible or unsafe request."""
    m = next((p for p in match.products if p.product_id == product_id), None)
    product = catalog.get(product_id)
    if m is None or product is None:
        raise DraftError("unknown_product")
    if m.status != "eligible":
        raise DraftError(f"product_{m.status}")
    safe = store.get(m.safe_amount_fact_id).value
    if isinstance(amount_minor, bool) or not isinstance(amount_minor, int) or amount_minor < product.min_amount_minor:
        raise DraftError("below_product_minimum")
    if amount_minor > safe:
        raise DraftError("over_repayment_safe_amount")

    pay = installment(amount_minor, product.monthly_rate, product.term_months)
    doc = {
        "schema": SCHEMA,
        "status": "draft",
        "synthetic_data": passport.synthetic_data,
        "as_of": passport.as_of.isoformat(),
        "business": {"id": passport.business_id, "name": passport.business_name},
        "currency": passport.currency,
        "product": {"id": product.id, "name": product.name, "lender": product.lender, "type": product.type,
                    "term_months": product.term_months, "monthly_rate": format(product.monthly_rate, ".6g")},
        "amount_minor": amount_minor,
        "installment_minor": pay,
        "total_repayable_minor": pay * product.term_months,
        "repayment_safety": {
            "max_installment_minor": store.get(match.max_installment_fact_id).value,
            "safe_amount_minor": safe,
            "max_installment_fact": match.max_installment_fact_id,
            "safe_amount_fact": m.safe_amount_fact_id,
        },
        "eligibility": [{"rule": r.rule, "passed": r.passed, "reason": render(r.reason, store).text}
                        for r in m.rules],
        "readiness": {"band": passport.band_id, "passport_sha256": passport_sha256},
        "disclaimer": ("Draft prepared from synthetic demo data. Sent only when the owner signs it. The lender makes "
                       "the credit decision. Not regulated financial advice."),
    }
    digest = canonical_hash(doc)
    return draft_id_for(digest), digest, doc
