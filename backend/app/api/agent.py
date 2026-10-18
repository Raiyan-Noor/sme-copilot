"""Agent routes: ask the planner a question, streamed over SSE for the UI or returned as JSON for /docs and tests.

Both run the same turn (agent/planner.py). Every number in a reply has passed the Numeric Firewall and links to its
fact (invariant 4); action events carry the gateway's decision, not the planner's description of it (invariant 1).
"""

import json
from typing import Annotated

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, TypeAdapter

from app.agent.context import CONVERSATION_ID_PATTERN, ConversationStore
from app.agent.events import AgentEvent, ReplyEvent
from app.agent.service import run_turn, start_turn
from app.api.deps import BusinessId, RuntimeDep

router = APIRouter(tags=["agent"])

_EVENT = TypeAdapter(AgentEvent)


class AskRequest(BaseModel):
    message: Annotated[str, Field(min_length=1, max_length=2000)]
    conversation_id: Annotated[str | None, Field(pattern=CONVERSATION_ID_PATTERN)] = None


class AgentTurn(BaseModel):
    conversation_id: str
    events: list[AgentEvent]
    reply: ReplyEvent


def _conversations(request: Request) -> ConversationStore:
    return request.app.state.conversations


@router.post("/businesses/{business_id}/agent/ask", response_model=AgentTurn)
def ask(business_id: BusinessId, body: AskRequest, request: Request, rt: RuntimeDep) -> AgentTurn:
    """Ask the planner and get the whole turn at once: tool calls, gateway decisions and the checked reply."""
    ctx = start_turn(rt, _conversations(request), business_id, body.conversation_id)
    events = list(run_turn(ctx, body.message, rt.llm))
    reply = next(e for e in reversed(events) if isinstance(e, ReplyEvent))
    return AgentTurn(conversation_id=ctx.conversation.id, events=events, reply=reply)


@router.post(
    "/businesses/{business_id}/agent/chat",
    response_class=StreamingResponse,
    responses={200: {"content": {"text/event-stream": {}},
                     "description": "Server-sent events: conversation, tool_call, action, error, reply; then done."}},
)
def chat(business_id: BusinessId, body: AskRequest, request: Request, rt: RuntimeDep) -> StreamingResponse:
    """Ask the planner and stream the turn as server-sent events. The reply arrives whole, after the firewall."""
    ctx = start_turn(rt, _conversations(request), business_id, body.conversation_id)
    llm = rt.llm

    def stream():
        for event in run_turn(ctx, body.message, llm):
            yield f"event: {event.type}\ndata: {_EVENT.dump_json(event).decode()}\n\n"
        yield f"event: done\ndata: {json.dumps({'conversation_id': ctx.conversation.id})}\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
