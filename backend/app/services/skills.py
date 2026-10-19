"""Custom skills: the built-in list, uploading and previewing a skill.md, and activating it for a new business.

An uploaded skill is untrusted input (packs/skill.py is the boundary). This module adds what needs the runtime:
- an upload is compiled, previewed and, if valid, staged content-addressed under data_dir/skills/<sha256>.skill.md;
  a staged file is re-checked against its hash whenever it is read;
- a skill cannot reuse a built-in skill's ID (it would shadow it), unless it is that very file;
- activation copies the staged file into the new business's own folder and records its hash in the business
  meta, so the business keeps running exactly the skill the owner previewed (services/businesses.custom_skill);
- uploads, rejections and activations are audit-logged (invariant 7), and an accepted upload's hash becomes an
  anchoring leaf (anchoring/service.py, invariant 9: the hash only, never the file).

Nothing here touches policy.yaml, tiers, caps or mandates: a skill only configures the engine.
"""

import hashlib
import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from app.packs.loader import builtin_skills
from app.packs.schema import AdvisorQuestion, DataNeed
from app.packs.skill import Badge, Skill, SkillError, parse_cached, parse_skill
from app.services.businesses import META_SKILL, SKILL_FILE, set_meta

SHA256 = re.compile(r"^[0-9a-f]{64}$")


class SkillRule(BaseModel):
    detector: str
    label: str


class SkillKpi(BaseModel):
    id: str
    label: str
    unit: str


class SkillPreview(BaseModel):
    """What the owner sees before activating a skill. Text is the skill's own wording: owner view only, never sent to
    the planner (invariant 2). `description` is Markdown, rendered as plain text by the client (no HTML)."""

    status: Literal["ok", "rejected"]
    filename: str | None = None
    sha256: str | None = None
    badge: Badge | None = None
    builtin: bool = False
    pack_id: str | None = None
    version: int | None = None
    display_name: str | None = None
    business_types: list[str] = []
    description: str = ""
    data_needs: list[DataNeed] = []
    questions: list[AdvisorQuestion] = []
    detectors: list[SkillRule] = []
    kpis: list[SkillKpi] = []
    notices: list[str] = []
    errors: list[str] = []


def _builtin_shas() -> dict[str, str]:
    return {s.sha256: pid for pid, s in builtin_skills().items()}


def preview_of(skill: Skill, filename: str | None = None) -> SkillPreview:
    p = skill.authored
    return SkillPreview(
        status="ok", filename=filename, sha256=skill.sha256, badge=skill.badge,
        builtin=skill.sha256 in _builtin_shas(), pack_id=p.id, version=p.version, display_name=p.display_name,
        business_types=list(p.business_types), description=skill.body, data_needs=list(p.data_needs),
        questions=list(p.advisor_questions),
        detectors=[SkillRule(detector=d.detector, label=d.label) for d in p.leak_detectors],
        kpis=[SkillKpi(id=k.id, label=k.label, unit=k.unit) for k in p.kpis], notices=list(skill.notices))


def list_builtin() -> list[SkillPreview]:
    """Specialist skills first (by name), the general fallback last."""
    from app.services.onboarding import FALLBACK_PACK

    skills = sorted(builtin_skills().items(), key=lambda kv: (kv[0] == FALLBACK_PACK, kv[1].pack.display_name))
    return [preview_of(s) for _, s in skills]


def _staged_dir(rt) -> Path:
    return rt.data_dir / "skills"


def upload(rt, filename: str, data: bytes) -> SkillPreview:
    """Compile an uploaded skill.md and stage it if valid. A refused file comes back with every error listed."""
    filename = Path(filename or "skill.md").name[:120]
    try:
        skill = parse_skill(data)
        builtin = skill.sha256 in _builtin_shas()
        if not builtin and skill.pack.id in builtin_skills():
            raise SkillError([f"id: {skill.pack.id!r} belongs to a built-in skill; give your skill its own id"])
    except SkillError as e:
        rt.audit.append("skill.rejected", {"bytes": len(data), "file_sha256": hashlib.sha256(data).hexdigest(),
                                           "errors": len(e.errors), "first_errors": [m[:160] for m in e.errors[:5]]})
        return SkillPreview(status="rejected", filename=filename, errors=e.errors[:50])
    folder = _staged_dir(rt)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{skill.sha256}.skill.md").write_text(skill.text, encoding="utf-8", newline="\n")
    rt.audit.append("skill.uploaded", {"sha256": skill.sha256, "pack_id": skill.pack.id,
                                       "version": skill.pack.version, "badge": skill.badge, "builtin": builtin,
                                       "notices": len(skill.notices), "bytes": len(data)})
    return preview_of(skill, filename)


def staged(rt, sha256: str) -> Skill:
    """A previously uploaded skill by hash. Raises SkillError if it is unknown or no longer matches its hash."""
    if not SHA256.match(sha256 or ""):
        raise SkillError(["unknown skill: upload it again"])
    path = _staged_dir(rt) / f"{sha256}.skill.md"
    try:
        skill = parse_cached(path.read_text(encoding="utf-8"))
    except OSError:
        raise SkillError(["unknown skill: upload it again"]) from None
    if skill.sha256 != sha256:
        raise SkillError(["the staged skill does not match its hash: upload it again"])
    return skill


def builtin_id(skill: Skill) -> str | None:
    """The built-in pack ID if this skill is byte-for-byte a built-in skill."""
    return _builtin_shas().get(skill.sha256)


def activate(rt, conn, business_id: str, skill: Skill) -> None:
    """Make a new business run this uploaded skill: its own copy, pinned by hash."""
    folder = rt.data_dir / business_id
    folder.mkdir(parents=True, exist_ok=True)
    (folder / SKILL_FILE).write_text(skill.text, encoding="utf-8", newline="\n")
    set_meta(conn, META_SKILL, skill.sha256)
    rt.audit.append("skill.activated", {"business_id": business_id, "sha256": skill.sha256,
                                        "pack_id": skill.pack.id, "badge": skill.badge})


def clear_staged(rt) -> int:
    """Delete staged uploads (rehearsal reset). Activated skills live with their business and go with it."""
    folder = _staged_dir(rt)
    files = list(folder.glob("*.skill.md")) if folder.is_dir() else []
    for f in files:
        f.unlink(missing_ok=True)
    return len(files)
