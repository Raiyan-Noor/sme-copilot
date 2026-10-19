"""The overnight job, run when the simulated clock moves forward: invoice reminders, then the Morning Brief.

Reminders (invariants 1, 3, 6): for every open customer invoice past its due date, the job proposes
`send_invoice_reminder` to the business's gateway, exactly as the planner's propose_action would. The gateway
alone decides: it executes only under the owner's signed standing mandate and inside every policy.yaml cap,
allow-list and frequency rule; otherwise it denies with the rule that fired. The job never touches an executor.
Arguments come from the business's own scheduled items, so they are `trusted`; an item whose due date came from an
untrusted source (e.g. the mailbox extractor) is skipped and reported instead of being proposed.

Brief: written after the reminders, so "done overnight" reports what the gateway actually executed.

Everything is logged (invariant 7): each proposal through the gateway's own decision log, plus a start and finish
entry for the run.
"""

from pydantic import BaseModel

from app.agent import brief as brief_writer
from app.agent.brief import MorningBrief, ReminderOutcome
from app.agent.context import load_profile
from app.agent.tools import TRUSTED_SCHEDULE_SOURCES
from app.gateway import ArgValue, Gateway, ProposedAction
from app.services.finance import Computed
from app.services.onboarding import skipped_hints

REMINDER_TOOL = "send_invoice_reminder"


class OvernightReport(BaseModel):
    business_id: str
    as_of: str
    reminders: list[ReminderOutcome]
    brief: MorningBrief


def overdue_reminders(computed: Computed, gateway: Gateway) -> list[ReminderOutcome]:
    """Propose a reminder for every overdue open receivable; return each gateway decision."""
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
    outcomes = overdue_reminders(computed, gateway) if reminders else []
    profile = load_profile(computed, rt.settings.seed_dir)
    brief = brief_writer.write(rt.llm, computed, profile, today, outcomes, gateway.store.pending_approvals(today),
                               rt.audit, could_also_check=skipped_hints(rt, business_id))
    brief_writer.save(rt.data_dir / business_id, brief)
    rt.audit.append("overnight.finished", {
        "business_id": business_id, "as_of": today.isoformat(),
        "reminders": {s: sum(o.status == s for o in outcomes)
                      for s in ("executed", "pending_approval", "denied", "skipped")},
        "brief_generated_by": brief.generated_by,
    })
    return OvernightReport(business_id=business_id, as_of=today.isoformat(), reminders=outcomes, brief=brief)
