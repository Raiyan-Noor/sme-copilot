"""The Morning Brief's activity feed: what the overnight run did, read back from the audit log (invariant 7).

Every row stands for real audit entries, and its time is that entry's simulated date and time of day (`AuditLog`
records it from `SimClock.now()`); nothing here makes a time up. An entry logged before the log kept times shows
its date only. Rows run oldest first. An entry kind with no special mapping still shows, as a plain "done" row.

Read-only: this proposes, approves and executes nothing. A row waiting for the owner carries only the IDs the
existing flows need: `approval_ids` for the approval sheet (the owner signs in the browser, the gateway verifies;
invariants 1 and 6) and `payment_key`/`payment_id` for the Payments flow, which proposes `pay_invoice` to the gateway
exactly as the Payments tab does. A held email carries no payment handle at all, so it can only be reviewed.

Text is code-written. Amounts and dates are `{fact:id}` placeholders resolved from `facts` (invariant 4). A held
email's sender name is shown to the owner only; nothing here reaches the planner (invariant 2).
"""

from datetime import date, timedelta
from typing import Literal

from pydantic import BaseModel

from app.agent import brief as brief_writer
from app.agent.brief import MorningBrief
from app.agent.context import load_profile
from app.audit import AuditEntry
from app.firewall.fact import Fact
from app.services.overnight import DRAFTABLE_RULES, EMAIL_TOOL, REMINDER_TOOL

RowKind = Literal["approval", "payment", "held", "insight", "done"]
RowState = Literal["waiting", "done", "blocked", "denied", "insight"]

PAY_TOOL = "pay_invoice"
PAYMENT_DUE_DAYS = 1  # payables due today or tomorrow are prepared for the owner to sign this morning
NEW_PAYEE_FLAGS = frozenset({"first_time_payee", "amount_anomaly"})  # the brief does not raise these as fraud

# Plain rows: what an audit entry kind says happened. Anything not listed is titled from its kind.
KIND_TITLES = {
    "overnight.started": "Overnight run started",
    "overnight.finished": "Overnight run finished",
    "engine.facts_computed": "Cash buffer recalculated",
    "llm.call": "Brief written",
    "clock.advanced": "Moved to the new day",
}


class Stamp(BaseModel):
    """Where a row's time comes from: one audit entry."""

    seq: int
    date: str
    time: str | None = None  # HH:MM:SS on the simulated clock; None for entries logged before the log kept times


class ActivityRow(BaseModel):
    id: str
    kind: RowKind
    state: RowState
    at: Stamp
    title: str
    detail: str = ""
    facts: dict[str, Fact] = {}
    tool: str | None = None
    approval_ids: list[str] = []  # still waiting for the owner's signature
    payment_key: str | None = None  # a suggested payment the Payments flow can start (POST payments/requests)
    payment_id: str | None = None  # an existing payment request
    email_id: str | None = None  # a held email, for review
    sender: str | None = None  # a held email's sender as shown to the owner
    flags: list[str] = []
    rule: str | None = None  # the gateway rule that refused it
    done_label: str | None = None  # Sent, Paid, Declined, Cancelled, Done
    completed: Stamp | None = None


class BriefActivity(BaseModel):
    business_id: str
    as_of: Fact
    business_name: str
    pack_name: str
    owner_first_name: str | None = None
    brief_at: Stamp | None = None  # the entry that recorded the brief being written
    rows: list[ActivityRow]  # oldest first


def _stamp(e: AuditEntry) -> Stamp:
    return Stamp(seq=e.seq, date=e.date, time=e.time)


def _theirs(e: AuditEntry, business_id: str) -> bool:
    """Entries of another business are never shown; entries that name no business (gateway, LLM) are kept only
    inside this business's run, where the overnight job logged them."""
    return e.data.get("business_id") in (None, business_id)


def _held_for_review(rec) -> bool:
    """A held email that the brief raises: not the owner's own setup upload held only for "new payee" flags."""
    flags = rec.sentinel.flags or []
    return rec.sentinel.hold and not (rec.source == "upload" and all(f.code in NEW_PAYEE_FLAGS for f in flags))


def _names(names: list[str]) -> str:
    if len(names) <= 1:
        return "".join(names)
    return f"{', '.join(names[:-1])} and {names[-1]}"


class _Log:
    """Index of the audit entries the feed looks up by approval or payment request."""

    def __init__(self, entries: list[AuditEntry]):
        self.entries = entries
        self.decided: dict[str, AuditEntry] = {}  # approval_id -> the proposal that created it
        self.closed: dict[str, AuditEntry] = {}  # approval_id -> the latest signature or decline
        self.payment: dict[str, AuditEntry] = {}  # request_id -> the latest send or status entry
        for e in entries:
            aid = e.data.get("approval_id")
            if e.kind == "gateway.decision" and aid:
                self.decided.setdefault(aid, e)
            elif e.kind in ("gateway.approval", "gateway.approval_declined") and aid:
                self.closed[aid] = e
            elif e.kind in ("payments.sent", "payments.webhook_received", "payments.status_checked",
                            "payments.failed", "payments.request_cancelled") and e.data.get("request_id"):
                self.payment[e.data["request_id"]] = e


def _close(row: ActivityRow, statuses: dict[str, str], log: _Log, done_label: str) -> ActivityRow:
    """Set a row's state from the gateway's own approval statuses and the audit entries that resolved them."""
    pending = [a for a, s in statuses.items() if s == "pending"]
    row.approval_ids = pending
    refusals = [log.closed[a] for a in pending if a in log.closed and log.closed[a].kind == "gateway.approval"
                and log.closed[a].data.get("status") == "denied"]
    if refusals:
        row.rule = refusals[-1].data.get("rule")
    if pending:
        row.state = "waiting"
        return row
    ends = [log.closed[a] for a in statuses if a in log.closed]
    row.completed = _stamp(max(ends, key=lambda e: e.seq)) if ends else None
    if any(s == "executed" for s in statuses.values()):
        row.state, row.done_label = "done", done_label
    elif statuses and all(s == "declined" for s in statuses.values()):
        row.state, row.done_label = "done", "Declined"
    else:
        row.state, row.done_label = "done", "Closed"
    return row


def build(rt, business_id: str) -> BriefActivity | None:
    """The feed for the latest Morning Brief, or None before the first brief exists."""
    from app.services.inbox import load_inbox

    brief: MorningBrief | None = brief_writer.latest(rt.data_dir / business_id)
    if brief is None:
        return None
    computed = rt.facts(business_id)
    profile = load_profile(computed, rt.settings.seed_dir)
    gateway = rt.gateway(business_id)
    entries = rt.audit.entries()
    log = _Log(entries)
    as_of = str(brief.as_of.value)
    rows: list[ActivityRow] = []

    # ---- The overnight run that wrote this brief: every entry between its start and finish.
    starts = [i for i, e in enumerate(entries) if e.kind == "overnight.started"
              and e.data.get("business_id") == business_id and e.data.get("as_of") == as_of]
    window: list[AuditEntry] = []
    if starts:
        i = starts[-1]
        end = next((j for j in range(i, len(entries)) if entries[j].kind == "overnight.finished"
                    and entries[j].data.get("business_id") == business_id), len(entries) - 1)
        window = [e for e in entries[i:end + 1] if _theirs(e, business_id)]
        computed_entries = [e for e in entries[:end + 1] if e.kind == "engine.facts_computed"
                            and e.data.get("business_id") == business_id and e.date == as_of]
        if computed_entries:
            window = sorted([computed_entries[-1], *window], key=lambda e: e.seq)
    brief_entry = next((e for e in reversed(window) if e.kind == "brief.generated"), None)
    brief_at = _stamp(brief_entry) if brief_entry else None
    anchor_at = brief_at or (Stamp(seq=window[-1].seq, date=window[-1].date, time=window[-1].time) if window
                             else Stamp(seq=log.entries[-1].seq if log.entries else 0, date=as_of))

    # ---- Emails drafted for the owner to sign (the overnight reminders, plus any still waiting in the Outbox).
    pending = gateway.store.pending_approvals(rt.clock.today())
    email_ids = [n.approval_id for n in brief.needs_you if n.tool == EMAIL_TOOL]
    email_ids += [a.id for a in pending if a.tool == EMAIL_TOOL and a.id not in email_ids]
    if email_ids:
        statuses, recipients, overnight = {}, [], True
        for aid in email_ids:
            approval = gateway.store.get_approval(aid)
            if approval is None:
                continue
            statuses[aid] = approval.status
            view = gateway.email_view(approval.args)
            if view:
                if view["recipient_name"] and view["recipient_name"] not in recipients:
                    recipients.append(view["recipient_name"])
                overnight = overnight and view["origin"] == "overnight"
        if any(s != "superseded" for s in statuses.values()):
            statuses = {a: s for a, s in statuses.items() if s != "superseded"}
            first = min((log.decided[a] for a in statuses if a in log.decided), key=lambda e: e.seq, default=None)
            n = len(statuses)
            noun = "invoice reminder" if overnight else "email"
            rows.append(_close(ActivityRow(
                id="emails", kind="approval", state="waiting", at=_stamp(first) if first else anchor_at,
                title=f"{n} {noun}{'s' if n != 1 else ''} drafted", detail=f"To {_names(recipients)}" if recipients
                else "", tool=EMAIL_TOOL), statuses, log, "Sent"))
            sent = sum(1 for st in statuses.values() if st == "executed")
            if rows[-1].state == "waiting" and sent:
                rows[-1].detail += f" · {sent} sent, {len(rows[-1].approval_ids)} to sign"

    # ---- Payables due now: the Payments flow prepares and the owner signs (pay_invoice, T3).
    store = rt.payments.store(business_id)
    requests = store.all()
    suggestions = {s.key: s for s in rt.payments.suggestions(business_id)}
    payment_approvals: set[str] = {r.approval_id for r in requests if r.approval_id}
    due_by = date.fromisoformat(as_of) + timedelta(days=PAYMENT_DUE_DAYS)
    for item in brief.coming_up:
        if item.kind != "payable" or date.fromisoformat(str(item.due.value)) > due_by:
            continue
        mine = [r for r in requests if r.scheduled_item_id == item.id]
        req = max(mine, key=lambda r: (r.created_on, r.id)) if mine else None
        sug = suggestions.get(f"item:{item.id}")
        if req is None and sug is None:
            continue
        payee = req.payee_name if req else sug.payee_name
        row = ActivityRow(
            id=f"pay:{item.id}", kind="payment", state="waiting", at=anchor_at,
            title="Supplier payment due" if (req.source_kind if req else sug.source_kind) == "invoice"
            else "Bill due", detail=f"{payee} · {{fact:{item.amount.id}}} · due {{fact:{item.due.id}}}",
            facts={item.amount.id: item.amount, item.due.id: item.due}, tool=PAY_TOOL,
            payment_key=None if req else sug.key, payment_id=req.id if req else None)
        if req is not None:
            if req.status in ("awaiting_approval", "proposed") and req.approval_id:
                approval = gateway.store.get_approval(req.approval_id)
                _close(row, {req.approval_id: approval.status if approval else "pending"}, log, "Paid")
            elif req.status in ("sent", "settled", "approved"):
                row.state, row.done_label = "done", "Paid" if req.status == "settled" else "Sent"
                end = log.payment.get(req.id) or log.closed.get(req.approval_id or "")
                row.completed = _stamp(end) if end else None
            elif req.status in ("denied", "failed"):
                row.state, row.rule = "denied", req.rule
                end = log.payment.get(req.id) or log.closed.get(req.approval_id or "")
                row.completed = _stamp(end) if end else None
            else:  # cancelled: the Payments tab can prepare it again
                row.state, row.done_label = "done", "Cancelled"
                end = log.payment.get(req.id)
                row.completed = _stamp(end) if end else None
        rows.append(row)

    # ---- Anything else the brief says needs the owner (signed in the approval sheet).
    for n in brief.needs_you:
        if n.tool == EMAIL_TOOL or n.approval_id in payment_approvals:
            continue
        approval = gateway.store.get_approval(n.approval_id)
        first = log.decided.get(n.approval_id)
        rows.append(_close(ActivityRow(
            id=f"apr:{n.approval_id}", kind="approval", state="waiting", at=_stamp(first) if first else anchor_at,
            title="", detail=n.summary, facts=brief.facts, tool=n.tool),
            {n.approval_id: approval.status if approval else "pending"}, log, "Done"))

    # ---- Held emails: blocked, review only. Their time is when the sentinel assessed them.
    assessed = {e.data.get("email_id"): e for e in entries if e.kind == "sentinel.assessed"
                and e.data.get("business_id") == business_id}
    for rec in load_inbox(rt, business_id):
        if not _held_for_review(rec):
            continue
        e = assessed.get(rec.email_id)
        rows.append(ActivityRow(
            id=f"held:{rec.email_id}", kind="held", state="blocked", at=_stamp(e) if e else anchor_at,
            title="Message held", detail="Payment blocked", email_id=rec.email_id,
            sender=rec.from_display_name or rec.from_address, flags=[f.code for f in rec.sentinel.flags or []]))

    # ---- The insight the brief raised.
    if brief.improve:
        imp = brief.improve
        rows.append(ActivityRow(
            id=f"insight:{imp.leak_id}", kind="insight", state="insight", at=anchor_at, title=imp.title,
            detail=imp.text, facts=imp.facts))

    # ---- Everything else the run logged, as plain rows (repeats of one kind in a row are folded together).
    held_before = sum(1 for r in rows if r.kind == "held" and brief_at and r.at.seq <= brief_at.seq)
    plain: list[ActivityRow] = []
    for e in window:
        if e.kind == "email.drafted":
            continue  # shown in the drafted emails row
        if e.kind == "gateway.decision":
            tool, status, rule = e.data.get("tool"), e.data.get("status"), e.data.get("rule")
            if tool == EMAIL_TOOL and status == "pending_approval":
                continue  # shown in the drafted emails row
            if tool == REMINDER_TOOL and status == "denied" and rule in DRAFTABLE_RULES:
                continue  # drafted as an email for the owner instead
            name = profile.counterparty_names.get(str(e.data.get("args", {}).get("customer_id", "")), "")
            what = "Invoice reminder" if tool == REMINDER_TOOL else (tool or "Action").replace("_", " ").capitalize()
            plain.append(ActivityRow(
                id=f"e{e.seq}", kind="done", state="done" if status == "executed" else "denied", at=_stamp(e),
                title=f"{what} {'sent' if status == 'executed' else 'not sent'}", detail=name, tool=tool,
                rule=rule if status != "executed" else None, done_label="Done" if status == "executed" else None))
            continue
        if e.kind == "brief.generated":
            to_sign = sum(1 for n in brief.needs_you if n.tool == EMAIL_TOOL)
            parts = [f"{held_before} email{'s' if held_before != 1 else ''} flagged"] if held_before else []
            parts += [f"{to_sign} to sign in outbox"] if to_sign else []
            plain.append(ActivityRow(id=f"e{e.seq}", kind="done", state="done", at=_stamp(e),
                                     title="Morning brief ready", detail=" · ".join(parts), done_label="Done"))
            continue
        detail, facts = "", {}
        if e.kind == "engine.facts_computed" and "cash.buffer_days" in brief.facts:
            detail, facts = "{fact:cash.buffer_days} of cash buffer", {"cash.buffer_days": brief.facts["cash.buffer_days"]}
        elif e.kind == "llm.call":
            detail = " · ".join(str(x) for x in (e.data.get("provider"), e.data.get("model")) if x)
        title = KIND_TITLES.get(e.kind, e.kind.replace(".", " ").replace("_", " ").capitalize())
        if plain and plain[-1].title == title and plain[-1].kind == "done" and e.kind not in KIND_TITLES:
            continue  # a burst of the same background entry (e.g. anchor checks) is one row
        plain.append(ActivityRow(id=f"e{e.seq}", kind="done", state="done", at=_stamp(e), title=title,
                                 detail=detail, facts=facts, done_label="Done"))

    owner = profile.owner_name.split()[0] if profile.owner_name and profile.owner_name != "the owner" else None
    return BriefActivity(
        business_id=business_id, as_of=brief.as_of, business_name=profile.business_name,
        pack_name=profile.pack_display_name, owner_first_name=owner, brief_at=brief_at,
        rows=sorted(rows + plain, key=lambda r: (r.at.seq, r.kind != "done")))
