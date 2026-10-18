"""Financing match, repayment-safe sizing, Readiness Passport and its canonical export (build prompt 13).

Required by the build prompt: one product fails a digital-history rule, and the nano loan passes and is capped.
Runs on the real seed through the production path (ingestion, pack categorization, services.finance.compute).
"""

import json
from datetime import date, timedelta

import pytest

from app.audit import canonical_hash
from app.audit.canonical import canonical_json
from app.clock import FixedClock
from app.engine.application import DraftError, build_draft, draft_id_for
from app.engine.catalog import RULES, load_catalog
from app.engine.financing import financing_metrics, installment, safe_principal
from app.firewall.digit_check import check_output
from app.firewall.render import render
from app.ledger.snapshot import LedgerSnapshot, Transaction
from app.packs.loader import load_pack
from app.services.finance import resolver
from app.services.financing import PassportExports, referenced_fact_ids, verify_passport_bytes
from app.services.runtime import Runtime
from tests.helpers import make_settings

MAYA = "maya-corner-store"
LINA = "lina-boutique"


@pytest.fixture(scope="module")
def rt(tmp_path_factory) -> Runtime:
    from data.seed.generate import generate

    root = tmp_path_factory.mktemp("financing")
    generate(root / "generated")
    runtime = Runtime(make_settings(data_dir=root / "tenants", seed_dir=root / "generated"))
    runtime.ensure_ready()
    return runtime


@pytest.fixture(scope="module")
def maya(rt):
    return rt.facts(MAYA)


def product(c, product_id):
    return next(p for p in c.financing.match.products if p.product_id == product_id)


def value(c, fact_id):
    return c.store.get(fact_id).value


# Catalog ------------------------------------------------------------------------------------------------------

def test_catalog_is_synthetic_with_six_to_ten_products_and_known_rules():
    catalog = load_catalog()
    assert catalog.synthetic is True and 6 <= len(catalog.products) <= 10
    assert all(r.rule in RULES for p in catalog.products for r in p.rules)
    assert all(not any(ch.isdigit() for ch in p.name + p.lender) for p in catalog.products)


# Required: digital-history failure and the capped nano loan ---------------------------------------------------

def test_digital_credit_line_fails_its_digital_history_rule(maya):
    p = product(maya, "prd_digital_line")
    assert p.status == "not_eligible" and not p.eligible
    rule = next(r for r in p.rules if r.rule == "min_digital_history_months")
    assert rule.passed is False
    assert value(maya, rule.metric_fact_id) < value(maya, rule.threshold_fact_id)  # six months of history vs twelve
    # The reason names both numbers as facts and says when the rule will be met.
    assert f"{{fact:{rule.metric_fact_id}}}" in rule.reason and "below the minimum" in rule.reason
    met_from = value(maya, rule.eligible_from_fact_id)
    assert met_from > maya.inputs.snapshot.transactions[-1].posted_on
    # The other rule on this product passes: the failure is the digital-history rule.
    assert [r.rule for r in p.rules if not r.passed] == ["min_digital_history_months"]


def test_nano_loan_passes_every_rule_and_is_capped_by_repayment_safety(maya):
    p = product(maya, "prd_nano")
    nano = load_catalog().get("prd_nano")
    assert p.status == "eligible" and all(r.passed for r in p.rules)
    assert p.capped_by == "repayment_safety"
    safe, cap = value(maya, p.safe_amount_fact_id), value(maya, "financing.capacity.max_installment")
    assert nano.min_amount_minor <= safe < nano.max_amount_minor
    assert value(maya, p.installment_fact_id) == installment(safe, nano.monthly_rate, nano.term_months) <= cap
    # One more step would break the cap: the size is the largest safe one.
    assert installment(safe + nano.step_minor, nano.monthly_rate, nano.term_months) > cap


def test_max_installment_is_the_smaller_of_the_stressed_surplus_and_liquidity_caps(maya):
    v = lambda k: value(maya, f"financing.capacity.{k}")  # noqa: E731
    assert v("stressed_monthly_surplus") == v("expected_monthly_net") - v("stress_loss")
    assert v("stress_loss") > 0 and v("revenue_drop") == load_catalog().sizing.revenue_drop
    assert v("max_installment") == max(0, min(v("surplus_cap"), v("liquidity_cap")))
    assert v("surplus_cap") <= v("stressed_monthly_surplus")


def test_every_rule_reports_pass_or_fail_with_a_firewall_clean_reason(maya):
    for p in maya.financing.match.products:
        assert p.rules
        for r in p.rules:
            assert check_output(r.reason, maya.store).ok, r.reason
            text = render(r.reason, maya.store).text
            assert ("meets" in text) == r.passed


def test_ranking_puts_eligible_first(maya):
    statuses = [p.status for p in maya.financing.match.products]
    assert statuses == sorted(statuses, key=["eligible", "not_safe", "not_eligible"].index)


def test_lina_nano_loan_is_capped_by_the_product_maximum(rt):
    """A business with more repayment capacity hits the product's own limit instead."""
    p = product(rt.facts(LINA), "prd_nano")
    assert p.status == "eligible" and p.capped_by == "product_max"
    assert value(rt.facts(LINA), p.safe_amount_fact_id) == load_catalog().get("prd_nano").max_amount_minor


# Sizing and metrics -----------------------------------------------------------------------------------------------

def test_safe_principal_respects_step_max_and_zero_capacity():
    nano = load_catalog().get("prd_nano")
    assert safe_principal(0, nano) == 0
    assert safe_principal(10**9, nano) == nano.max_amount_minor
    p = safe_principal(50_000, nano)
    assert p % nano.step_minor == 0 and installment(p, nano.monthly_rate, nano.term_months) <= 50_000


def _row(i: int, day: date, amount: int, category: str) -> Transaction:
    return Transaction(id=f"t{i}", account_id="a", posted_on=day, amount_minor=amount, currency="USD",
                       description="x", category=category, import_id="i", source_line=i)


def test_digital_history_restarts_after_a_gap():
    pack = load_pack("grocery_retail")
    today = date(2026, 10, 19)
    days = [date(2025, 10, 1), date(2025, 11, 1)] + [today - timedelta(days=d) for d in range(70, 0, -5)]
    snap = LedgerSnapshot(business_id="b", currency="USD",
                          transactions=tuple(_row(i, d, 1000, "sales_wallet") for i, d in enumerate(days)))
    facts = {f.id: f for f in financing_metrics(snap, pack, FixedClock(today))}
    assert facts["financing.metric.history_months"].value == 12
    assert facts["financing.metric.digital_history_months"].value == 2  # the run restarted after the gap
    assert facts["financing.metric.digital_share"].value == 1.0


# Passport --------------------------------------------------------------------------------------------------------

def test_passport_band_reasons_and_path(maya):
    pp = maya.financing.passport
    assert pp.band_id == maya.financing.readiness.band_id and pp.synthetic_data is True
    assert {f.factor for f in pp.factors} == {"inflow_regularity", "revenue_stability", "buffer_days",
                                              "collection_days", "payment_punctuality"}
    assert pp.reasons and pp.path_to_eligibility
    for text in [*pp.reasons, *(s.text for s in pp.path_to_eligibility)]:
        assert check_output(text, maya.store).ok, text
    assert "prd_nano" in pp.eligible_product_ids
    assert any(s.kind == "product" and s.product_id == "prd_digital_line" for s in pp.path_to_eligibility)
    if pp.next_band_label:
        assert any(s.kind == "readiness" for s in pp.path_to_eligibility)


def test_readiness_raw_factors_trace_to_ledger_and_invoices(maya):
    resolve = resolver(maya.inputs)
    for name in ("collection_days", "payment_punctuality"):
        fact = maya.store.get(f"passport.raw.{name}")
        kinds = {resolve(ref).kind for ref in fact.source_row_ids}
        assert "transaction" in kinds and kinds & {"receivable", "supplier_invoice"}, (name, kinds)


def test_every_financing_fact_traces(maya):
    resolve = resolver(maya.inputs)
    for fid in referenced_fact_ids(maya.financing):
        fact = maya.store.get(fid)
        assert all(i in maya.store for i in fact.inputs), fid
        for ref in fact.source_row_ids:
            assert ref.startswith(("clock:", "pack:", "catalog:")) or resolve(ref) is not None, (fid, ref)


def test_passport_export_is_canonical_hashed_logged_and_deterministic(rt, maya, tmp_path):
    exports = PassportExports(tmp_path / "passports")
    first = exports.export(MAYA, maya.financing, maya.store, rt.audit)
    again = exports.export(MAYA, maya.financing, maya.store, rt.audit)
    assert first.sha256 == again.sha256 == canonical_hash(first.document)
    data = (tmp_path / "passports" / f"{first.sha256}.json").read_bytes()
    assert data == canonical_json(first.document) and verify_passport_bytes(data) == first.sha256
    assert "facts" in first.document and first.document["band"]["id"] == maya.financing.passport.band_id
    logged = [e for e in rt.audit.entries() if e.kind == "passport.exported"]
    assert logged[-1].data["sha256"] == first.sha256 and logged[-1].data["business_id"] == MAYA
    assert [e.sha256 for e in exports.list()] == [first.sha256]


def test_tampered_passport_export_is_not_served(rt, maya, tmp_path):
    exports = PassportExports(tmp_path / "passports")
    item = exports.export(MAYA, maya.financing, maya.store, rt.audit)
    path = tmp_path / "passports" / f"{item.sha256}.json"
    doc = json.loads(path.read_bytes())
    doc["band"]["id"] = "ready"
    path.write_bytes(canonical_json(doc))
    assert exports.get(item.sha256) is None and exports.list() == []
    assert verify_passport_bytes(path.read_bytes()) != item.sha256


# Draft applications -----------------------------------------------------------------------------------------------

def _draft(c, product_id, amount):
    return build_draft(match=c.financing.match, passport=c.financing.passport, passport_sha256="0" * 64,
                       store=c.store, catalog=load_catalog(), product_id=product_id, amount_minor=amount)


def test_draft_is_content_addressed_and_carries_rule_results(maya):
    safe = value(maya, product(maya, "prd_nano").safe_amount_fact_id)
    draft_id, sha, doc = _draft(maya, "prd_nano", safe)
    assert sha == canonical_hash(doc) and draft_id == draft_id_for(sha) and not any(ch.isdigit() for ch in draft_id)
    assert doc["amount_minor"] == safe and doc["status"] == "draft"
    assert all(r["passed"] for r in doc["eligibility"]) and doc["readiness"]["passport_sha256"] == "0" * 64


@pytest.mark.parametrize("product_id,amount,rule", [
    ("prd_nano", "safe+step", "over_repayment_safe_amount"),
    ("prd_nano", 100, "below_product_minimum"),
    ("prd_digital_line", 200_000, "product_not_eligible"),
    ("prd_nope", 100_000, "unknown_product"),
])
def test_draft_refused_outside_eligibility_or_safe_size(maya, product_id, amount, rule):
    if amount == "safe+step":
        amount = value(maya, product(maya, "prd_nano").safe_amount_fact_id) + load_catalog().get("prd_nano").step_minor
    with pytest.raises(DraftError) as exc:
        _draft(maya, product_id, amount)
    assert exc.value.rule == rule
