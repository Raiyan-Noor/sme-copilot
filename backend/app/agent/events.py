"""Events a planner turn emits, streamed to the UI over SSE and returned together by the JSON endpoint.

The reply is emitted once, whole, after the Numeric Firewall has passed it (invariant 4); it is never streamed
token by token, because the owner must not see text the firewall has not checked. Tool and action events stream as
they happen. Stage events say what the planner loop is doing right now, so the UI can show a status line while the
owner waits; they carry a stage code and, for tool stages, the tool name. No event carries raw untrusted text
(invariant 2) or an LLM-written digit.
"""

from typing import Annotated, Literal

from pydantic import BaseModel, Field


class ReplySegment(BaseModel):
    text: str
    fact_id: str | None = None  # set when this segment is a rendered fact: the UI links it to explain_fact


class ConversationEvent(BaseModel):
    type: Literal["conversation"] = "conversation"
    conversation_id: str
    today_fact_id: str


Stage = Literal["received", "thinking", "tool", "action", "firewall", "fixing"]


class StageEvent(BaseModel):
    """Progress through the planner loop. Emitted before each step starts, so the UI's line matches the wait."""

    type: Literal["stage"] = "stage"
    stage: Stage
    tool: str | None = None  # set for stage="tool": the read tool about to run


class ToolCallEvent(BaseModel):
    type: Literal["tool_call"] = "tool_call"
    tool: str
    ok: bool
    fact_ids: list[str] = []  # facts this call handed the planner


class ActionEvent(BaseModel):
    """The gateway's decision on a proposal, straight from the gateway (not from the planner's words)."""

    type: Literal["action"] = "action"
    tool: str
    status: Literal["executed", "pending_approval", "denied"]
    rule: str | None = None
    effective_tier: str | None = None
    approval_id: str | None = None
    requires_out_of_band_call: bool = False
    untrusted_args: list[str] = []
    reason: str
    reason_segments: list[ReplySegment] = []


class FirewallReport(BaseModel):
    attempts: int  # planner drafts checked
    rejected: list[list[str]] = []  # violation kinds per rejected draft
    fallback: bool = False  # true: the owner sees template text, not the planner's words


class ReplyEvent(BaseModel):
    type: Literal["reply"] = "reply"
    text: str
    segments: list[ReplySegment]
    fact_ids: list[str]
    firewall: FirewallReport


class ErrorEvent(BaseModel):
    type: Literal["error"] = "error"
    kind: Literal["llm_unavailable", "replay_miss", "step_limit"]
    message: str


AgentEvent = Annotated[ConversationEvent | StageEvent | ToolCallEvent | ActionEvent | ReplyEvent | ErrorEvent,
                       Field(discriminator="type")]
