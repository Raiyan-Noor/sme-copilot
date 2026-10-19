"""skill.md compiling: built-in skills round-trip and verify, the community bakery skill compiles, and bad skills are
refused with clear errors (feature plan P8). The attack cases are in tests/redteam/test_skill_attacks.py."""

from pathlib import Path

import pytest
import yaml
from nacl.signing import SigningKey

from app.packs import library_key
from app.packs.loader import SKILLS_DIR, builtin_skills, list_pack_ids, load_pack
from app.packs.skill import MAX_SKILL_BYTES, SkillError, parse_skill, skill_content, skill_sha256

BAKERY = SKILLS_DIR / "bakery.skill.md"


def text_of(name: str) -> str:
    return (SKILLS_DIR / name).read_text(encoding="utf-8")


def skill_from(doc: dict, body: str = "# Test\n\nA test skill.\n") -> str:
    return f"---\n{yaml.safe_dump(doc, sort_keys=False)}---\n\n{body}"


def bakery_doc() -> dict:
    return yaml.safe_load(skill_content(BAKERY.read_text(encoding="utf-8"))[1])


def errors_of(data: str | bytes) -> list[str]:
    with pytest.raises(SkillError) as e:
        parse_skill(data)
    return e.value.errors


def test_builtin_skills_are_verified_and_keep_their_wording():
    assert list_pack_ids() == ["fashion_retail", "general_retail", "grocery_retail"]
    for pack_id, skill in builtin_skills().items():
        assert skill.verified and skill.badge == "verified", pack_id
        assert skill.pack == skill.authored  # verified: the planner sees the skill's own labels
        assert skill.body.startswith("# ")
    assert load_pack("grocery_retail").categories["fresh_produce"].label == "Fresh produce and dairy"


def test_bakery_is_a_valid_community_skill():
    skill = parse_skill(BAKERY.read_bytes())
    assert skill.badge == "community" and not skill.verified and not skill.notices
    assert skill.pack.id == "bakery" and skill.pack.id not in list_pack_ids()
    assert [q.id for q in skill.pack.advisor_questions] == [
        "unsold_bake", "cake_deposits", "ingredient_prices", "cafe_accounts", "wallet_fees"]
    grocery = {q.id for q in load_pack("grocery_retail").advisor_questions}
    assert grocery != {q.id for q in skill.pack.advisor_questions}


def test_unverified_skill_runs_with_labels_rebuilt_from_ids():
    skill = parse_skill(BAKERY.read_bytes())
    assert skill.authored.categories["flour_grain"].label == "Flour and grain"
    assert skill.pack.categories["flour_grain"].label == "Flour grain"
    assert skill.pack.display_name == "Bakery"
    assert [d.label for d in skill.pack.leak_detectors][3] == "Supplier price creep"
    assert {b.label for b in skill.pack.readiness.bands} == {"Ready", "Building", "Early"}
    assert all(f.reason == "Fit set by this skill" for f in skill.pack.financing_fit.values())
    # Owner-only onboarding text is kept: it is shown to the owner and never sent to the planner.
    assert skill.pack.advisor_questions == skill.authored.advisor_questions
    assert skill.pack.data_needs == skill.authored.data_needs


def test_signature_line_is_outside_the_hash_and_any_edit_unverifies():
    text = text_of("grocery.skill.md")
    unsigned = skill_content(text)[0]
    assert "signature:" not in unsigned and skill_sha256(text) == skill_sha256(unsigned)
    assert parse_skill(unsigned).badge == "community"
    tampered = text.replace("Benchmarks in this skill are synthetic", "Benchmarks in this skill are real")
    assert parse_skill(tampered).badge == "community"


def test_signature_by_another_key_is_not_verified():
    text = skill_content(text_of("fashion.skill.md"))[0]
    sha = skill_sha256(text)
    other = SigningKey.generate().encode().hex()
    forged = text.replace("\n---\n", f'\nsignature: "{library_key.sign(sha, other)}"\n---\n', 1)
    assert skill_sha256(forged) == sha and parse_skill(forged).badge == "community"
    assert not library_key.verify(sha, "ed25519:not-base64!")
    assert not library_key.verify(sha, None)


def test_crlf_and_bom_do_not_change_the_hash():
    text = BAKERY.read_text(encoding="utf-8")
    assert parse_skill(("﻿" + text.replace("\n", "\r\n")).encode()).sha256 == parse_skill(text).sha256


@pytest.mark.parametrize("data, needle", [
    ("# Just markdown\n", "frontmatter"),
    ("---\nid: [unclosed\n---\n", "not valid YAML"),
    ("---\n- a list\n---\n", "mapping"),
    (b"---\nid: \xff\n---\n", "UTF-8"),
])
def test_malformed_files_are_refused_clearly(data, needle):
    assert any(needle in m for m in errors_of(data))


def test_every_schema_problem_is_listed():
    doc = bakery_doc()
    doc["colour"] = "pink"
    doc["kpis"][0]["healthy"] = {"min": 0.9, "max": 0.1}
    doc["seasonality"]["months"].pop(12)
    errors = errors_of(skill_from(doc))
    assert "colour: unknown field: it is not part of the skill format" in errors
    assert any(m.startswith("kpis.0.healthy") for m in errors)
    assert any(m.startswith("seasonality.months") for m in errors)


def test_unknown_detector_and_bad_params_are_refused():
    doc = bakery_doc()
    doc["leak_detectors"].append({"detector": "send_money", "label": "x", "params": {}})
    doc["leak_detectors"][1]["params"]["max_share_of_digital"] = 4
    errors = errors_of(skill_from(doc))
    assert any("unknown detector 'send_money'" in m for m in errors)
    assert any("bad params for detector payment_fees" in m for m in errors)


def test_size_limit():
    big = BAKERY.read_text(encoding="utf-8") + "x" * MAX_SKILL_BYTES
    assert errors_of(big) == [f"the file is larger than {MAX_SKILL_BYTES // 1024} KB"]


def test_library_skills_and_readme_exist():
    assert {p.name for p in SKILLS_DIR.glob("*.skill.md")} >= {"grocery.skill.md", "fashion.skill.md",
                                                               "bakery.skill.md"}
    assert (SKILLS_DIR / "README.md").is_file()
    assert (Path(__file__).resolve().parents[3] / "docs" / "skills" / "FORMAT.md").is_file()


def test_the_format_doc_example_validates():
    doc = (Path(__file__).resolve().parents[3] / "docs" / "skills" / "FORMAT.md").read_text(encoding="utf-8")
    example = doc.split("## Minimal example", 1)[1].split("```markdown\n", 1)[1].split("\n```\n", 1)[0] + "\n"
    skill = parse_skill(example)
    assert skill.pack.id == "flower_shop" and skill.badge == "community"
    assert [d.detector for d in skill.pack.leak_detectors] == ["payment_fees", "slow_moving_stock"]
