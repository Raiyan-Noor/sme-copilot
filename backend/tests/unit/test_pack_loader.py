"""Skill Pack validation: the built-in skills load, and bad packs fail at load time, not at run time."""

from pathlib import Path

import pytest
import yaml

from app.engine.pack_inputs import build_engine_pack
from app.packs.loader import SKILLS_DIR, PackError, list_pack_ids, load_pack, load_pack_file, load_skill_file
from app.packs.registry import DetectorParams, detector, registered_names
from app.packs.skill import skill_content


def _doc(name: str = "grocery") -> dict:
    _, front, _ = skill_content((SKILLS_DIR / f"{name}.skill.md").read_text(encoding="utf-8"))
    doc = yaml.safe_load(front)
    doc.pop("signature", None)
    return doc


def _write(tmp_path: Path, doc: dict, name: str = "grocery") -> Path:
    path = tmp_path / f"{name}.skill.md"
    path.write_text(f"---\n{yaml.safe_dump(doc, sort_keys=False)}---\n\n# Test\n", encoding="utf-8")
    return path


def test_builtin_packs_load():
    assert list_pack_ids() == ["fashion_retail", "general_retail", "grocery_retail"]
    for pack_id in list_pack_ids():
        pack = load_pack(pack_id)
        assert pack.id == pack_id and pack.benchmarks_synthetic is True


def test_every_referenced_detector_is_registered():
    names = set(registered_names())
    for pack_id in list_pack_ids():
        assert {d.detector for d in load_pack(pack_id).leak_detectors} <= names


def test_engine_doc_builds_an_engine_pack():
    pack = load_pack("grocery_retail")
    engine = build_engine_pack(pack.engine_doc(), [])
    assert engine.pack_id == "grocery_retail"
    assert engine.kind_of("fresh_produce", -1) == "cogs"
    assert engine.is_scheduled("rent") and not engine.is_scheduled("repairs_maintenance")
    assert set(engine.month_multipliers) == set(range(1, 13))


def test_unknown_pack_id_is_refused():
    with pytest.raises(PackError, match="unknown pack"):
        load_pack("../gateway/policy")


def _mutate_and_expect(tmp_path: Path, mutate, match: str) -> None:
    doc = _doc()
    mutate(doc)
    with pytest.raises(PackError, match=match):
        load_pack_file(_write(tmp_path, doc))


def test_unknown_detector_name_fails(tmp_path):
    _mutate_and_expect(tmp_path, lambda d: d["leak_detectors"].append(
        {"detector": "move_money", "label": "x", "params": {}}), "unknown detector")


def _detector(doc: dict, name: str) -> dict:
    return next(d for d in doc["leak_detectors"] if d["detector"] == name)


def test_unknown_detector_param_fails(tmp_path):
    _mutate_and_expect(tmp_path, lambda d: _detector(d, "late_fees")["params"].update(run_shell=True), "bad params")


def test_detector_param_out_of_range_fails(tmp_path):
    _mutate_and_expect(tmp_path, lambda d: _detector(d, "payment_fees")["params"].update(max_share_of_digital=3),
                       "bad params")


def test_detector_naming_unknown_category_fails(tmp_path):
    _mutate_and_expect(tmp_path, lambda d: _detector(d, "duplicate_subscription")["params"].update(categories=["nope"]),
                       "unknown categories")


def test_readiness_weights_must_sum_to_one(tmp_path):
    _mutate_and_expect(tmp_path, lambda d: d["readiness"]["factors"]["buffer_days"].update(weight=0.5),
                       "weights must sum to 1")


def test_readiness_needs_all_factors(tmp_path):
    _mutate_and_expect(tmp_path, lambda d: d["readiness"]["factors"].pop("collection_days"), "exactly the factors")


def test_kpi_must_reference_known_categories(tmp_path):
    _mutate_and_expect(tmp_path, lambda d: d["kpis"][0].update(numerator=["unknown_cat"]), "unknown categories")


def test_months_must_cover_the_year(tmp_path):
    _mutate_and_expect(tmp_path, lambda d: d["seasonality"]["months"].pop(12), "months")


def test_only_revenue_can_be_digital(tmp_path):
    _mutate_and_expect(tmp_path, lambda d: d["categories"]["rent"].update(digital=True), "digital")


def test_benchmarks_must_be_marked_synthetic(tmp_path):
    _mutate_and_expect(tmp_path, lambda d: d.update(benchmarks_synthetic=False), "benchmarks_synthetic")


def test_extra_top_level_keys_are_rejected(tmp_path):
    _mutate_and_expect(tmp_path, lambda d: d.update(actions=["pay_anyone"]), "actions")


def test_unchanged_doc_round_trips(tmp_path):
    # Unsigned, so the copy runs with planner-safe labels; its own wording is unchanged.
    assert load_skill_file(_write(tmp_path, _doc())).authored == load_pack("grocery_retail")


def test_detector_names_are_unique():
    class P(DetectorParams):
        pass

    with pytest.raises(ValueError, match="already registered"):
        detector("late_fees", P)(lambda df, p, ctx: [])
