"""The hand-rolled planner loop (invariants 1, 2, 4, 5, 7).

One turn: system prompt (prompts/planner.md) + conversation history + the owner's message go to the LLM adapter
with the read tools and propose_action. Tool calls run in code and their results go back; this repeats until the
planner replies in text or MAX_STEPS calls have been made.

Every draft reply passes the Numeric Firewall against the turn's FactStore before the owner sees it. A rejected
draft gets one re-prompt naming what was wrong; if the next draft fails too (or the planner runs out of steps, or
the LLM is unavailable), the owner gets template text built in code from the facts the tools returned, so the
owner never sees a digit the LLM wrote. Rejected drafts are logged and kept out of the conversation history.

The planner holds no executor and no gateway: actions go through actions.propose_action, which calls the gateway.
"""

import hashlib
import json
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any, Protocol

from app.agent.actions import PROPOSE_ACTION_SCHEMA, propose_action
from app.agent.context import TODAY_FACT_ID, TurnContext
from app.agent.events import (
    ActionEvent,
    ConversationEvent,
    ErrorEvent,
    FirewallReport,
    ReplyEvent,
    ReplySegment,
    StageEvent,
    ToolCallEvent,
)
from app.agent.tools import READ_TOOLS, Tool, run_tool
from app.firewall.digit_check import CheckResult, ViolationKind, check_output
from app.firewall.render import render
from app.llm.adapter import LLMError
from app.llm.cache import ReplayMiss

PROMPT_PATH = Path(__file__).resolve().parents[1] / "llm" / "prompts" / "planner.md"
MAX_STEPS = 8
FIREWALL_REPROMPTS = 1
MAX_OUTPUT_TOKENS = 900
FALLBACK_FACTS = 8


class ChatClient(Protocol):
    """The slice of llm.adapter.LLMAdapter the planner uses (tests pass a scripted fake)."""

    def chat(self, role: str, messages: list[dict[str, Any]], *, tools: list[dict[str, Any]] | None = None,
             tool_choice: str | dict[str, Any] | None = None, max_output_tokens: int | None = None) -> Any: ...


def system_prompt(ctx: TurnContext) -> str:
    text = PROMPT_PATH.read_text(encoding="utf-8")
    text = text.split("-->", 1)[1] if "-->" in text else text  # drop the title and the loader comment
    p = ctx.profile
    for key, value in {
        "business_name": p.business_name,
        "pack_display_name": p.pack_display_name.lower(),
        "owner_name": p.owner_name,
        "today_fact": "{fact:" + TODAY_FACT_ID + "}",
        "currency": p.currency,
    }.items():
        text = text.replace("{{" + key + "}}", value)
    return text.strip()


def _correction(result: CheckResult, empty: bool) -> str:
    if empty:
        problem = "it was empty"
    else:
        kinds = {v.kind for v in result.violations}
        parts = []
        if ViolationKind.DIGIT in kinds:
            parts.append("it contains digits outside {fact:<id>} placeholders")
        if ViolationKind.MALFORMED_PLACEHOLDER in kinds:
            parts.append("it has a malformed placeholder (write exactly {fact:<id>})")
        unknown = sorted({v.snippet for v in result.violations if v.kind == ViolationKind.UNKNOWN_FACT})
        if unknown:
            parts.append("it cites fact IDs no tool returned: " + ", ".join(unknown))
        problem = "; ".join(parts)
    return (f"[Numeric Firewall] Your reply was rejected and not shown to the owner: {problem}. Rewrite the whole "
            "reply. Write every amount, date, count, percentage and ID only as a {fact:<id>} placeholder from a "
            "tool result, or leave it out. Name customers and payees instead of writing their IDs.")


def fallback_text(ctx: TurnContext, *, unavailable: bool = False) -> str:
    """Template reply built in code: the facts this turn's tools returned, with their labels. No LLM words."""
    if unavailable:
        head = "I can't reach the assistant right now."
    else:
        head = "I couldn't word that answer safely."
    lines = [f"- {label}: {{fact:{fid}}}" for fid, label in list(ctx.cited.items())[:FALLBACK_FACTS]]
    if not lines:
        return head + " Please try asking again, a little more specifically."
    return head + " Here are the figures I looked up:\n" + "\n".join(lines)


class _Timer:
    """Wall-clock latency of one turn, for the audit log: when the first stage went out, each LLM call, the total.

    Elapsed time only (time.perf_counter), never business time: that comes from clock.py.
    """

    def __init__(self):
        self.start = time.perf_counter()
        self.llm_ms: list[int] = []

    def ms(self, since: float | None = None) -> int:
        return round((time.perf_counter() - (self.start if since is None else since)) * 1000)

    def report(self, first_stage_ms: int) -> dict[str, Any]:
        return {"first_stage_ms": first_stage_ms, "llm_ms": self.llm_ms, "llm_total_ms": sum(self.llm_ms),
                "total_ms": self.ms()}


class Planner:
    def __init__(self, llm: ChatClient, read_tools: tuple[Tool, ...] = READ_TOOLS):
        self.llm = llm
        self.tools = {t.name: t for t in read_tools}
        self.schemas = [t.schema() for t in read_tools] + [PROPOSE_ACTION_SCHEMA]

    def run(self, ctx: TurnContext, message: str) -> Iterator[ConversationEvent | ToolCallEvent | ActionEvent |
                                                                  ReplyEvent | ErrorEvent]:
        conv = ctx.conversation
        self._timer = timer = _Timer()
        yield ConversationEvent(conversation_id=conv.id, today_fact_id=TODAY_FACT_ID)
        yield StageEvent(stage="received")
        self._first_stage_ms = timer.ms()
        ctx.audit.append("agent.turn_started", {
            "conversation_id": conv.id, "business_id": ctx.business_id, "history_messages": len(conv.messages),
            "message_sha256": hashlib.sha256(message.encode()).hexdigest(), "message_chars": len(message),
        })

        messages = [{"role": "system", "content": system_prompt(ctx)}, *conv.messages]
        turn = [{"role": "user", "content": message}]
        messages += turn
        rejected: list[list[str]] = []
        drafts = 0

        for _ in range(MAX_STEPS):
            yield StageEvent(stage="fixing" if rejected and messages[-1]["role"] == "user" else "thinking")
            began = time.perf_counter()
            try:
                result = self.llm.chat("planner", messages, tools=self.schemas, max_output_tokens=MAX_OUTPUT_TOKENS)
                timer.llm_ms.append(timer.ms(began))
            except (LLMError, ReplayMiss) as exc:
                timer.llm_ms.append(timer.ms(began))
                kind = "replay_miss" if isinstance(exc, ReplayMiss) else "llm_unavailable"
                yield ErrorEvent(kind=kind, message="The assistant is unavailable, so this reply uses a template.")
                yield self._finish(ctx, None, drafts, rejected, unavailable=True)
                return

            if result.tool_calls:
                assistant = result.assistant_message()
                messages.append(assistant)
                turn.append(assistant)
                for call in result.tool_calls:
                    yield (StageEvent(stage="action") if call.name == "propose_action"
                           else StageEvent(stage="tool", tool=call.name if call.name in self.tools else None))
                    content, events = self._call(ctx, call)
                    yield from events
                    tool_msg = {"role": "tool", "tool_call_id": call.id, "content": json.dumps(content)}
                    messages.append(tool_msg)
                    turn.append(tool_msg)
                continue

            text = (result.content or "").strip()
            drafts += 1
            yield StageEvent(stage="firewall")
            check = check_output(text, ctx.store)
            if text and check.ok:
                conv.messages += turn + [{"role": "assistant", "content": text}]
                yield self._finish(ctx, text, drafts, rejected)
                return

            kinds = sorted({v.kind.value for v in check.violations}) or ["empty"]
            rejected.append(kinds)
            ctx.audit.append("agent.firewall_rejected", {
                "conversation_id": conv.id, "draft": drafts, "violations": kinds,
                "violation_count": len(check.violations), "unknown_fact_ids": sorted(
                    {v.snippet for v in check.violations if v.kind == ViolationKind.UNKNOWN_FACT}),
            })
            if len(rejected) > FIREWALL_REPROMPTS:
                break
            # The rejected draft and the correction go to the planner for this turn only, never into history.
            messages += [{"role": "assistant", "content": text},
                         {"role": "user", "content": _correction(check, not text)}]
        else:
            yield ErrorEvent(kind="step_limit", message="The assistant took too many steps; showing the figures.")

        template = fallback_text(ctx)
        conv.messages += turn + [{"role": "assistant", "content": template}]
        yield self._finish(ctx, template, drafts, rejected, fallback=True)

    def _call(self, ctx: TurnContext, call: Any) -> tuple[dict[str, Any], list]:
        before = set(ctx.cited)
        action: ActionEvent | None = None
        if call.name == "propose_action":
            content, action = propose_action(ctx, call.arguments)
        elif call.name in self.tools:
            content = run_tool(self.tools[call.name], ctx, call.arguments)
        else:
            content = {"error": f"no tool named {call.name}; use propose_action for actions"}
        fact_ids = [f for f in ctx.cited if f not in before]
        ok = "error" not in content
        ctx.audit.append("agent.tool_call", {
            "conversation_id": ctx.conversation.id, "tool": call.name, "ok": ok,
            "arguments_sha256": hashlib.sha256((call.arguments or "").encode()).hexdigest(),
            "fact_ids": fact_ids, "error": content.get("error"),
            "action_status": action.status if action else None,
        })
        events: list = [ToolCallEvent(tool=call.name, ok=ok, fact_ids=fact_ids)]
        if action:
            events.append(action)
        return content, events

    def _finish(self, ctx: TurnContext, text: str | None, drafts: int, rejected: list[list[str]], *,
                fallback: bool = False, unavailable: bool = False) -> ReplyEvent:
        if text is None:
            text = fallback_text(ctx, unavailable=unavailable)
            fallback = True
        rendered = render(text, ctx.store)  # re-checks the firewall: there is no path around it
        report = FirewallReport(attempts=drafts, rejected=rejected, fallback=fallback)
        ctx.audit.append("agent.reply", {
            "conversation_id": ctx.conversation.id, "fact_ids": list(rendered.fact_ids), "drafts": drafts,
            "rejected": rejected, "fallback": fallback, "llm_unavailable": unavailable,
            "timing": self._timer.report(self._first_stage_ms),
        })
        return ReplyEvent(text=rendered.text, fact_ids=list(rendered.fact_ids), firewall=report,
                          segments=[ReplySegment(text=s.text, fact_id=s.fact_id) for s in rendered.segments])
