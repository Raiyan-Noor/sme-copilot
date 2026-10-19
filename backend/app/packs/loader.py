"""Load the built-in Skill Packs: the skill.md files listed in BUILTIN_FILES, from the repo's skills/ library.

Every skill, built-in or uploaded, compiles through packs/skill.py: the Pydantic schema, then every referenced
detector must be registered and its params must validate against that detector's params model, every category a
detector names must exist in the pack, and every onboarding answer that sets a detector param must be a valid value
for it. A bad pack fails loudly here instead of producing wrong numbers later.

Only the files named below are built in; the other skills in the library (community examples) are uploaded like any
custom skill. A business that activated an uploaded skill resolves it through services/businesses.business_pack.
"""

from functools import lru_cache
from pathlib import Path

from app.config import REPO_ROOT
from app.packs.schema import Pack
from app.packs.skill import PackError, Skill, SkillError, parse_cached

__all__ = ["BUILTIN_FILES", "SKILLS_DIR", "PackError", "SkillError", "builtin_skill", "builtin_skills",
           "list_pack_ids", "load_pack", "load_pack_file", "load_skill_file"]

SKILLS_DIR = REPO_ROOT / "skills"
BUILTIN_FILES = ("fashion.skill.md", "general.skill.md", "grocery.skill.md")


def load_skill_file(path: Path) -> Skill:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        raise PackError(f"cannot read skill {path.name}: {e}") from None
    try:
        return parse_cached(text)
    except SkillError as e:
        raise SkillError([f"{path.name}: {m}" for m in e.errors]) from None


def load_pack_file(path: Path) -> Pack:
    """Parse and fully validate one skill file; the pack the app runs."""
    return load_skill_file(path).pack


@lru_cache
def builtin_skills() -> dict[str, Skill]:
    """Built-in skills by pack ID."""
    found: dict[str, Skill] = {}
    for name in BUILTIN_FILES:
        skill = load_skill_file(SKILLS_DIR / name)
        if skill.pack.id in found:
            raise PackError(f"two built-in skills declare the pack id {skill.pack.id!r}")
        found[skill.pack.id] = skill
    return found


def list_pack_ids() -> list[str]:
    return sorted(builtin_skills())


def builtin_skill(pack_id: str) -> Skill:
    """A built-in skill by pack ID. Only IDs of the built-in files resolve (no path input)."""
    skills = builtin_skills()
    if pack_id not in skills:
        raise PackError(f"unknown pack {pack_id!r}; available: {sorted(skills)}")
    return skills[pack_id]


def load_pack(pack_id: str) -> Pack:
    return builtin_skill(pack_id).pack
