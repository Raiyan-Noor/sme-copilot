"""Skills: the built-in list, and uploading a custom skill.md for a preview. Thin routes over services/skills.py.

A preview never activates anything: the owner confirms it, and onboarding then creates the business with the
previewed skill's hash (POST /onboarding with `skill_sha256`).
"""

from typing import Annotated

from fastapi import APIRouter, File, UploadFile

from app.api.deps import RuntimeDep
from app.packs.skill import MAX_SKILL_BYTES
from app.services import skills
from app.services.skills import SkillPreview

router = APIRouter(tags=["skills"])


@router.get("/skills", response_model=list[SkillPreview])
def get_skills() -> list[SkillPreview]:
    """The built-in skills, each with its badge and what it asks and watches."""
    return skills.list_builtin()


@router.post("/skills/preview", response_model=SkillPreview)
async def preview_skill(rt: RuntimeDep, file: Annotated[UploadFile, File(description="A skill.md file")]
                        ) -> SkillPreview:
    """Validate an uploaded skill.md and show what it would do. A refused file lists every error found."""
    data = await file.read(MAX_SKILL_BYTES + 1)
    return skills.upload(rt, file.filename or "skill.md", data)
