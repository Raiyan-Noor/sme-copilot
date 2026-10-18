"""Wire one planner turn to the runtime: the business's facts, gateway, clock, audit log and the LLM adapter."""

from collections.abc import Iterator

from app.agent.context import Conversation, ConversationStore, TurnContext, load_profile
from app.agent.planner import ChatClient, Planner
from app.services.inbox import load_inbox
from app.services.runtime import Runtime


def start_turn(rt: Runtime, conversations: ConversationStore, business_id: str,
               conversation_id: str | None) -> TurnContext:
    """Build the turn's context. Raises TenantError for an unknown business before any streaming starts."""
    computed = rt.facts(business_id)
    gateway = rt.gateway(business_id)
    conv: Conversation = conversations.get_or_create(business_id, conversation_id)
    return TurnContext(conversation=conv, computed=computed, clock=rt.clock, audit=rt.audit, gateway=gateway,
                       profile=load_profile(computed, rt.settings.seed_dir), inbox=load_inbox(rt, business_id))


def run_turn(ctx: TurnContext, message: str, llm: ChatClient) -> Iterator:
    """Run the turn holding the conversation's lock, so two turns never interleave in one history."""
    with ctx.conversation.lock:
        yield from Planner(llm).run(ctx, message)
