"""Every leak planted in the seed is found by the business's own pack, about the right subject, with the planted
evidence rows and a yearly impact close to the manifest's ground truth. The manifest is test-only (never read by
app code)."""

import json

import pytest

from app.ledger.purchases import load_purchases_csv
from app.packs.leaks import find_leaks, run_leak_detectors
from app.packs.loader import load_pack
from tests.golden.pipeline import load_business

BUSINESSES = {"maya_corner_store": "grocery_retail", "lina_boutique": "fashion_retail"}
LEAK_DETECTORS = {"supplier_price_creep", "duplicate_subscription", "payment_fees", "unprofitable_products",
                  "missed_early_pay_discounts", "late_fees", "slow_moving_stock"}


@pytest.fixture(scope="module")
def seeded(tmp_path_factory):
    from data.seed.generate import generate

    root = tmp_path_factory.mktemp("seed")
    generate(root / "generated")
    manifest = json.loads((root / "generated" / "manifest.json").read_text(encoding="utf-8"))
    out = {}
    for biz, pack_id in BUSINESSES.items():
        b = load_business(root / "generated", biz, root / "tenants")
        purchases = load_purchases_csv(root / "generated" / biz / "purchases.csv")
        kw = {"products": b.products, "sale_lines": b.sale_lines, "purchases": purchases}
        out[biz] = (b, load_pack(pack_id), kw, find_leaks(b.snapshot, load_pack(pack_id), b.clock, **kw))
    return manifest, out


def _planted(manifest):
    return [a for a in manifest["anomalies"] if a.get("expected_detection", {}).get("detector") in LEAK_DETECTORS]


def _finding_for(anomaly, findings):
    """The finding of the anomaly's detector about its subject (counterparty IDs are not in ledger rows)."""
    detector = anomaly["expected_detection"]["detector"]
    subject = {k: v for k, v in anomaly["expected_detection"].get("subject", {}).items() if k != "counterparty_id"}
    hits = [f for f in findings if f.detector == detector and subject.items() <= f.subject.items()]
    assert len(hits) == 1, f"{anomaly['id']}: {len(hits)} matching findings"
    return hits[0]


def test_every_planted_leak_is_found_about_its_subject(seeded):
    manifest, out = seeded
    planted = _planted(manifest)
    assert {a["expected_detection"]["detector"] for a in planted} == LEAK_DETECTORS
    for a in planted:
        detector = a["expected_detection"]["detector"]
        _, _, _, findings = out[a["business_id"]]
        hits = [f for f in findings if f.detector == detector]
        assert hits, f"{a['id']}: {detector} found nothing"
        subject = {k: v for k, v in a["expected_detection"].get("subject", {}).items() if k != "counterparty_id"}
        assert any(subject.items() <= f.subject.items() for f in hits), f"{a['id']}: wrong subject"


def test_purchase_and_sale_evidence_is_the_planted_rows(seeded):
    manifest, out = seeded
    for a in _planted(manifest):
        _, _, kw, findings = out[a["business_id"]]
        detector = a["expected_detection"]["detector"]
        f = _finding_for(a, findings)
        evidence = set(f.impact.source_row_ids)
        if detector == "supplier_price_creep":
            assert evidence == set(a["evidence"]["row_ids"])
        elif detector == "missed_early_pay_discounts":
            invoices = {ln.invoice_id for ln in kw["purchases"] if ln.id in evidence}
            assert invoices == set(a["evidence"]["invoice_ids"])
        elif detector == "unprofitable_products":
            pid = a["facts"]["product_id"]
            assert evidence and all(s.product_id == pid for s in kw["sale_lines"] if s.id in evidence)


def test_yearly_impact_is_close_to_ground_truth(seeded):
    manifest, out = seeded
    checked = 0
    for a in _planted(manifest):
        truth = a["facts"].get("yearly_impact_minor")
        detector = a["expected_detection"]["detector"]
        if truth is None or detector in ("payment_fees", "late_fees"):
            continue  # payment fees: the pack reports only the excess; late fees: window differs, see below
        f = _finding_for(a, out[a["business_id"]][3])
        # The manifest annualizes over the whole seed history; detectors annualize over the span since the first
        # evidence row (Lina's first jeans purchase is two weeks into the history), so allow that gap.
        assert f.impact.value == pytest.approx(truth, rel=0.10), a["id"]
        checked += 1
    assert checked == 6  # two price creeps, two duplicate subscriptions, the loss product, missed discounts


def test_late_fee_is_annualized_over_the_lookback(seeded):
    manifest, out = seeded
    [a] = [a for a in _planted(manifest) if a["expected_detection"]["detector"] == "late_fees"]
    _, pack, _, findings = out[a["business_id"]]
    [f] = [f for f in findings if f.detector == "late_fees"]
    lookback = next(d.params["lookback_days"] for d in pack.leak_detectors if d.detector == "late_fees")
    assert f.impact.value == round(a["facts"]["total_minor"] * 365 / lookback)


def test_no_false_positives_on_the_seed(seeded):
    manifest, out = seeded
    planted = {(a["business_id"], a["expected_detection"]["detector"]) for a in _planted(manifest)}
    for biz, (_, _, _, findings) in out.items():
        for f in findings:
            assert (biz, f.detector) in planted, f"{biz}: unexpected {f.id}"
        per_detector = [f.detector for f in findings]
        assert len(per_detector) == len(set(per_detector)), f"{biz}: duplicate findings {per_detector}"


def test_every_leak_fact_traces_to_rows_and_is_deterministic(seeded):
    _, out = seeded
    for b, pack, kw, findings in out.values():
        for f in findings:
            assert f.impact.unit == "money" and f.impact.value > 0 and f.impact.source_row_ids
            for d in f.details:
                assert d.id.startswith(f.id + ".") and (d.source_row_ids or d.inputs)
        assert run_leak_detectors(b.snapshot, pack, b.clock, **kw) == run_leak_detectors(b.snapshot, pack, b.clock,
                                                                                          **kw)


def test_detectors_without_pos_data_find_nothing_instead_of_failing(seeded):
    _, out = seeded
    b, pack, _, _ = out["maya_corner_store"]
    detectors = {f.detector for f in find_leaks(b.snapshot, pack, b.clock)}
    assert detectors.isdisjoint({"supplier_price_creep", "unprofitable_products", "missed_early_pay_discounts",
                                 "slow_moving_stock"})


def test_the_pack_decides_which_detectors_run_on_the_same_data(seeded):
    _, out = seeded
    b, _, kw, _ = out["lina_boutique"]
    as_grocery = {f.detector for f in find_leaks(b.snapshot, load_pack("grocery_retail"), b.clock, **kw)}
    as_fashion = {f.detector for f in find_leaks(b.snapshot, load_pack("fashion_retail"), b.clock, **kw)}
    # Grocery keeps stock 30 days before calling it slow and sells through faster; same jacket, both flag it, but
    # the carrying cost rate differs, so the impact differs.
    assert "slow_moving_stock" in as_grocery and "slow_moving_stock" in as_fashion
    g = next(f for f in find_leaks(b.snapshot, load_pack("grocery_retail"), b.clock, **kw)
             if f.detector == "slow_moving_stock")
    f = next(f for f in find_leaks(b.snapshot, load_pack("fashion_retail"), b.clock, **kw)
             if f.detector == "slow_moving_stock")
    assert g.impact.value != f.impact.value
