"""Financing fit from the pack: how well each financing product type suits this kind of business.

Used by the financing matcher (build prompt 13) to rank eligible products. Fit is a ranking input, not an
eligibility rule: eligibility stays with each product's machine-readable rules.
"""

from app.packs.schema import FinancingFit, FinancingProductType, Pack

NOT_LISTED = FinancingFit(fit=0.0, reason="Not a typical fit for this type of business")


def financing_fit(pack: Pack, product_type: FinancingProductType) -> FinancingFit:
    return pack.financing_fit.get(product_type, NOT_LISTED)


def rank_product_types(pack: Pack, product_types: list[FinancingProductType]) -> list[FinancingProductType]:
    """Best fit first; ties keep the input order."""
    return sorted(product_types, key=lambda t: -financing_fit(pack, t).fit)
