"""Live demo console routes. Mounted only when DEMO_MODE is on (main.py); in normal mode these paths do not exist.

A simulated sender for recording the demo: it delivers preset or custom mail into the sandbox mailbox through the
real inbox pipeline (services/demo_console.py). It sends no real email and cannot trigger an action.
"""

from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from app.api.deps import BusinessId, RuntimeDep
from app.services import demo_console as console
from app.services.demo_console import Preset, SendResult

router = APIRouter(tags=["demo-console"])

MAX_ATTACHMENT = 3 * 1024 * 1024
ATTACHMENT_TYPES = {"application/pdf": ("application", "pdf"), "image/png": ("image", "png"),
                    "image/jpeg": ("image", "jpeg")}


class PresetSend(BaseModel):
    preset: str


class ConsoleInfo(BaseModel):
    presets: list[Preset]
    rule_based_checks: list[str]  # still catch fraud when every model call fails
    model_assisted_checks: list[str]


@router.get("/businesses/{business_id}/demo/console", response_model=ConsoleInfo)
def console_info(business_id: BusinessId, rt: RuntimeDep) -> ConsoleInfo:
    """The preset buttons for this business, and which sentinel checks are rule-based versus model-assisted."""
    return ConsoleInfo(presets=console.presets_for(rt, business_id), rule_based_checks=list(console.RULE_BASED_CHECKS),
                       model_assisted_checks=list(console.MODEL_ASSISTED_CHECKS))


@router.post("/businesses/{business_id}/demo/send-preset", response_model=SendResult)
def send_preset(business_id: BusinessId, body: PresetSend, rt: RuntimeDep) -> SendResult:
    """Deliver one preset email: live model, then the sentinel. Progress streams on the inbox SSE feed meanwhile."""
    try:
        return console.send(rt, business_id, preset=body.preset)
    except console.ConsoleError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post("/businesses/{business_id}/demo/send-custom", response_model=SendResult)
async def send_custom(
    business_id: BusinessId, rt: RuntimeDep,
    sender_name: Annotated[str, Form()] = "", sender_email: Annotated[str, Form()] = "",
    subject: Annotated[str, Form()] = "", body: Annotated[str, Form()] = "", reply_to: Annotated[str, Form()] = "",
    attachment: UploadFile | None = File(default=None),
) -> SendResult:
    """Deliver a composed email (spoofed sender allowed), with an optional PDF or image attachment."""
    payload = None
    if attachment is not None and attachment.filename:
        kind = ATTACHMENT_TYPES.get((attachment.content_type or "").lower())
        data = await attachment.read(MAX_ATTACHMENT + 1)
        if kind is None:
            raise HTTPException(422, "attachments must be a PDF, PNG or JPEG")
        if len(data) > MAX_ATTACHMENT:
            raise HTTPException(413, "attachment too large")
        payload = (attachment.filename, kind[0], kind[1], data)
    try:
        return console.send(rt, business_id, custom=console.Draft(sender_name, sender_email, subject, body,
                                                                  reply_to, payload))
    except console.ConsoleError as exc:
        raise HTTPException(422, str(exc)) from exc
