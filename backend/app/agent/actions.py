"""propose_action: the planner's only way to ask for anything to happen (invariant 1).

The planner never executes. This tool turns its proposal into a gateway `ProposedAction` and returns exactly the
gateway's status (`executed`, `pending_approval` or `denied`) and rule. What it adds before the gateway sees it:

- Numbers come from facts, not from the planner (invariant 4). An amount or date argument is written as
  `{"fact": "<id>"}` citing a fact a tool returned this conversation, and code substitutes the fact's value.
  A literal number is refused, so the planner cannot invent or alter an amount.
- Provenance is decided here, never by the planner (invariant 3). A string argument is `trusted` only if a trusted
  tool result handed that exact value to the planner; a fact argument is trusted unless it came from quarantined
  content. Anything else (a value it made up or copied from the owner's message) is `untrusted`, so the gateway
  forces owner approval.
- The `reason` passes the Numeric Firewall, because the owner sees it on the approval card.

Tool names are free text on purpose: a request for a Tier 4 action (prices, hiring, large debt) reaches the gateway,
which denies it as an unknown tool and logs a violation (invariant 5).
"""

import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.agent.context import TurnContext
from app.agent.events import ActionEvent, ReplySegment
from app.firewall.digit_check import check_output
from app.firewall.render import render
from app.gateway import ArgValue, Decision, ProposedAction, load_policy
from app.gateway.dispatch import ACTION_ARGS


def _is_fact_arg(name: str, typ: type) -> bool:
    return typ is int or name.endswith("date")


def action_catalog() -> str:
    """The actions the gateway knows, with their exact argument names, generated from dispatch.ACTION_ARGS and
    policy.yaml so the planner's view can never drift from what the gateway accepts. Words only, no tier numbers:
    the planner would echo them. A Tier 4 action is absent by design (invariant 5)."""
    policy = load_policy()
    parts = []
    for tool, spec in ACTION_ARGS.items():
        args = ", ".join(n + ("=fact" if _is_fact_arg(n, t) else "") for n, t in spec.items())
        how = "runs within the owner's standing limit" if tool in policy.t2 else "waits for the owner's signature"
        parts.append(f"{tool}({args}): {how}")
    return "; ".join(parts)


PROPOSE_ACTION_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "propose_action",
        "description": (
            "Ask the gateway to carry out an action for the owner. It checks the owner's signed policy and returns "
            "executed, pending_approval or denied. Arguments: IDs exactly as tool results gave them; every amount "
            "or date (marked =fact) as {\"fact\": \"<fact id>\"} citing a fact from a tool result, never a number. "
            "The only actions that exist, with their exact arguments: " + action_catalog() + "."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "tool": {"type": "string", "description": "The action, e.g. send_invoice_reminder."},
                "args": {
                    "type": "object",
                    "description": "Action arguments: ID strings, or {\"fact\": \"<id>\"} for amounts and dates.",
                    "additionalProperties": True,
                },
                "reason": {"type": "string", "description": "One sentence for the owner, numbers as placeholders."},
            },
            "required": ["tool", "args", "reason"],
            "additionalProperties": False,
        },
    },
}


class ProposeArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool: str = Field(min_length=1, max_length=64)
    args: dict[str, Any] = {}
    reason: str = Field(min_length=1, max_length=500)


class ArgError(ValueError):
    pass


def _resolve(ctx: TurnContext, name: str, raw: Any) -> ArgValue:
    if isinstance(raw, dict):
        if set(raw) != {"fact"} or not isinstance(raw["fact"], str):
            raise ArgError(f"{name}: an object argument must be exactly {{\"fact\": \"<id>\"}}")
        fact_id = raw["fact"].removeprefix("{fact:").removesuffix("}")
        if fact_id not in ctx.store:
            raise ArgError(f"{name}: fact {fact_id} did not come from a tool result in this conversation")
        fact = ctx.store.get(fact_id)
        if fact.unit in ("money", "count") and isinstance(fact.value, int):
            value: str | int = fact.value
        elif fact.unit == "date" and fact.value is not None:
            value = fact.value.isoformat()
        else:
            raise ArgError(f"{name}: a {fact.unit} fact cannot be an action argument")
        return ArgValue(value=value, provenance=ctx.provenance_of_fact(fact_id))
    if isinstance(raw, bool) or isinstance(raw, (int, float)):
        raise ArgError(f"{name}: write amounts and dates as {{\"fact\": \"<id>\"}}, never as a number")
    if isinstance(raw, str):
        if len(raw) > 128:
            raise ArgError(f"{name}: too long")
        return ArgValue(value=raw, provenance=ctx.provenance_of_value(raw))
    raise ArgError(f"{name}: unsupported argument type")


def propose_action(ctx: TurnContext, raw_arguments: str) -> tuple[dict[str, Any], ActionEvent | None]:
    """Run one proposal. Returns (what the planner sees, the event the owner's UI sees)."""
    try:
        parsed = json.loads(raw_arguments or "{}")
        call = ProposeArgs.model_validate(parsed if isinstance(parsed, dict) else {})
        args = {name: _resolve(ctx, name, raw) for name, raw in call.args.items()}
        action = ProposedAction(tool=call.tool, args=args)
    except json.JSONDecodeError:
        return {"error": "arguments are not valid JSON"}, None
    except ValidationError as exc:
        return {"error": "invalid proposal: " + "; ".join(e["msg"] for e in exc.errors())}, None
    except ArgError as exc:
        return {"error": str(exc)}, None

    reason_check = check_output(call.reason, ctx.store)
    if not reason_check.ok:
        return {"error": "reason rejected by the Numeric Firewall: write numbers only as {fact:<id>} "
                         "placeholders from tool results"}, None

    decision: Decision = ctx.gateway.propose(action)
    rendered = render(call.reason, ctx.store)
    event = ActionEvent(
        tool=decision.tool,
        status=decision.status,
        rule=decision.rule,
        effective_tier=decision.effective_tier,
        approval_id=decision.approval.approval_id if decision.approval else None,
        requires_out_of_band_call=bool(decision.approval and decision.approval.requires_out_of_band_call_script),
        untrusted_args=action.untrusted(),
        reason=rendered.text,
        reason_segments=[ReplySegment(text=s.text, fact_id=s.fact_id) for s in rendered.segments],
    )
    # The planner gets the status and rule only: no approval ID or executor output, which carry digits.
    seen: dict[str, Any] = {"status": decision.status, "tool": decision.tool}
    if decision.status == "denied":
        seen["rule"] = decision.rule
    elif decision.status == "pending_approval":
        seen["waiting_for"] = "owner_signature"
        seen["why"] = decision.rule
        if event.requires_out_of_band_call:
            seen["requires_out_of_band_call"] = True
    return seen, event
