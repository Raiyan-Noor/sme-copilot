"""The overnight job, run when the simulated clock moves forward: invoice reminders, then the Morning Brief.

Reminders (invariants 1, 3, 6): for every open customer invoice past its due date, the job proposes
`send_invoice_reminder` to the business's gateway, exactly as the planner's propose_action would. The gateway
alone decides: it executes only under the owner's signed standing mandate and inside every policy.yaml cap,
allow-list and frequency rule; otherwise it denies with the rule that fired. The job never touches an executor.
Arguments come from the business's own scheduled items, so they are `trusted`; an item whose due date came from an
untrusted source (e.g. the mailbox extractor) is skipped and reported instead of being proposed.

Drafting (invariants 1, 4, 6): when the gateway will not run a reminder on its own because the owner has signed no
standing limit for it (no mandate, customer not on the list, or the invoice is above a cap), the job drafts the same
reminder as an email for the owner to sign (`send_email`, T3). The text is a fixed template whose amount and due date
are fact placeholders rendered through the Numeric Firewall; it names no invoice number and no one else's data. It
goes through the gateway like any proposal, so it waits for the owner's signature and shows up in the Morning Brief.
A reminder already drafted and still waiting is not drafted again. A frequency cap is never worked around.

Brief: written after the reminders, so "done overnight" reports what the gateway actually executed.

Everything is logged (invariant 7): each proposal through the gateway's own decision log, plus a start and finish
entry for the run.
"""

from datetime import timedelta

from pydantic import BaseModel

from app.agent import brief as brief_writer
from app.agent.brief import MorningBrief, ReminderOutcome
from app.agent.context import Profile, load_profile
from app.agent.email_compose import EmailRejected, compose
from app.agent.tools import TRUSTED_SCHEDULE_SOURCES
from app.engine.scheduled import scheduled_prefix
from app.gateway import ArgValue, Gateway, ProposedAction
from app.gateway.emails import build_draft
from app.services.finance import Computed
from app.services.onboarding import skipped_hints

REMINDER_TOOL = "send_invoice_reminder"
EMAIL_TOOL = "send_email"
REMINDER_WINDOW_DAYS = 3  # the same window as the T2 frequency cap: a signed reminder is not drafted again sooner
# Why a reminder did not run on its own that the owner can fix by signing it themselves.
DRAFTABLE_RULES = frozenset({"no_standing_mandate", "not_allowlisted:customer_id", "over_policy_cap",
                             "over_mandate_cap"})


class OvernightReport(BaseModel):
    business_id: str
    as_of: str
    reminders: list[ReminderOutcome]
    brief: MorningBrief


def _waiting_reminder(gateway: Gateway, scheduled_item_id: str) -> str | None:
    """The approval ID of a reminder email already drafted for this invoice and still waiting, if any."""
    for approval in gateway.store.pending_approvals(gateway.clock.today()):
        view = gateway.email_view(approval.args) if approval.tool == EMAIL_TOOL else None
        if view and view["about"].get("scheduled_item_id") == scheduled_item_id:
            return approval.id
    return None


def draft_reminder_email(computed: Computed, profile: Profile, gateway: Gateway, item, customer_id: str
                         ) -> ReminderOutcome:
    """Draft the reminder as an email and propose it; the gateway decides (it waits for the owner's signature)."""
    invoice_id = item.reference or item.id
    waiting = _waiting_reminder(gateway, item.id)
    if waiting:
        return ReminderOutcome(scheduled_item_id=item.id, invoice_id=invoice_id, customer_id=customer_id,
                               status="pending_approval", rule="tier_T3", approval_id=waiting, tool=EMAIL_TOOL)
    since = gateway.clock.today() - timedelta(days=REMINDER_WINDOW_DAYS - 1)
    if any(m["kind"] == "email" and (m.get("about") or {}).get("scheduled_item_id") == item.id
           and m["on_date"] >= since.isoformat() for m in gateway.outbox()):
        return ReminderOutcome(scheduled_item_id=item.id, invoice_id=invoice_id, customer_id=customer_id,
                               status="denied", rule="frequency_cap", tool=EMAIL_TOOL)
    prefix = scheduled_prefix(item.id)
    name = profile.counterparty_names.get(customer_id, "")
    amount, due, overdue = (f"{{fact:{prefix}.{k}}}" for k in ("amount", "due_date", "days_overdue"))
    try:
        composed = compose(
            computed.store,
            "A friendly reminder about your open invoice",
            f"Hello{' ' + name if name else ''},\n\nThis is a friendly reminder that your invoice for {amount} was "
            f"due on {due}. If you have already paid it, thank you, and please ignore this message.\n\n"
            f"Kind regards,\n{profile.business_name}",
            f"The invoice is {overdue} overdue and no reminder limit covers it, so this reminder needs your "
            "signature.")
    except EmailRejected as exc:  # a template that fails the firewall is a bug; report it, send nothing
        return ReminderOutcome(scheduled_item_id=item.id, invoice_id=invoice_id, customer_id=customer_id,
                               status="denied", rule=exc.rule, tool=EMAIL_TOOL)
    draft_id, _ = gateway.save_email_draft(build_draft(
        recipient_id=customer_id, subject=composed.subject, body=composed.body, reason=composed.reason,
        origin="overnight", facts=composed.facts, about={"scheduled_item_id": item.id, "invoice_id": invoice_id}))
    decision = gateway.propose(ProposedAction(tool=EMAIL_TOOL, args={
        "recipient_id": ArgValue(value=customer_id, provenance="trusted"),
        "draft_id": ArgValue(value=draft_id, provenance="trusted")}))
    return ReminderOutcome(
        scheduled_item_id=item.id, invoice_id=invoice_id, customer_id=customer_id, status=decision.status,
        rule=decision.rule, approval_id=decision.approval.approval_id if decision.approval else None,
        tool=EMAIL_TOOL)


def overdue_reminders(computed: Computed, gateway: Gateway, profile: Profile | None = None
                      ) -> list[ReminderOutcome]:
    """Propose a reminder for every overdue open receivable; return each gateway decision. With a `profile`, a
    reminder the owner's limits do not cover is drafted as an email for the owner to sign."""
    today = gateway.clock.today()
    outcomes = []
    for item in computed.inputs.scheduled:
        if item.kind != "receivable" or item.status != "open" or item.due_date >= today:
            continue
        invoice_id = item.reference or item.id
        if item.source not in TRUSTED_SCHEDULE_SOURCES or not item.counterparty_id:
            outcomes.append(ReminderOutcome(scheduled_item_id=item.id, invoice_id=invoice_id,
                                            customer_id=item.counterparty_id, status="skipped",
                                            rule="untrusted_source"))
            continue
        trusted = {"customer_id": item.counterparty_id, "invoice_id": invoice_id,
                   "invoice_amount_minor": item.amount_minor}
        action = ProposedAction(tool=REMINDER_TOOL,
                                args={k: ArgValue(value=v, provenance="trusted") for k, v in trusted.items()})
        decision = gateway.propose(action)
        if profile is not None and decision.status == "denied" and decision.rule in DRAFTABLE_RULES:
            outcomes.append(draft_reminder_email(computed, profile, gateway, item, item.counterparty_id))
            continue
        outcomes.append(ReminderOutcome(
            scheduled_item_id=item.id, invoice_id=invoice_id, customer_id=item.counterparty_id,
            status=decision.status, rule=decision.rule, mandate_id=decision.mandate_id,
            approval_id=decision.approval.approval_id if decision.approval else None))
    return outcomes


def run_overnight(rt, business_id: str, *, reminders: bool = True) -> OvernightReport:
    """Reminders (optional), then the brief, for one business as of the simulated today. Saves the brief."""
    computed = rt.facts(business_id)
    gateway = rt.gateway(business_id)
    today = rt.clock.today()
    rt.audit.append("overnight.started", {"business_id": business_id, "as_of": today.isoformat(),
                                          "reminders": reminders})
    profile = load_profile(computed, rt.settings.seed_dir)
    outcomes = overdue_reminders(computed, gateway, profile) if reminders else []
    pending = gateway.store.pending_approvals(today)
    emails = {a.id: v for a in pending if a.tool == EMAIL_TOOL and (v := gateway.email_view(a.args))}
    brief = brief_writer.write(rt.llm, computed, profile, today, outcomes, pending, rt.audit,
                               could_also_check=skipped_hints(rt, business_id), emails=emails)
    brief_writer.save(rt.data_dir / business_id, brief)
    rt.audit.append("overnight.finished", {
        "business_id": business_id, "as_of": today.isoformat(),
        "reminders": {s: sum(o.status == s for o in outcomes)
                      for s in ("executed", "pending_approval", "denied", "skipped")},
        "brief_generated_by": brief.generated_by,
    })
    return OvernightReport(business_id=business_id, as_of=today.isoformat(), reminders=outcomes, brief=brief)
