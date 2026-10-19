"""The Morning Brief: written by the brief_writer LLM role from a bundle built in code (invariants 2, 4, 7).

The bundle holds only fact placeholders, enums, pack labels and the business's own counterparty and product names:
no fact values, no statement or email text. The draft must pass the Numeric Firewall against the facts the bundle
cited (no digit outside a `{fact:<id>}` placeholder, no unknown fact ID). A rejected draft gets one re-prompt; if
that fails too, or the LLM is unavailable, the brief is template text built here from the same bundle, so the owner
never sees a digit the LLM wrote.

Product and ad insights (best and worst margins, slow movers, stock about to run out, campaigns losing money, best
channel) are structured sections built in code from engine facts, shown next to the prose; they are not part of the
LLM bundle. `could_also_check` lists what the owner skipped at onboarding and what adding it would unlock.

The brief reports actions exactly as the gateway decided them: `executed_actions` lists only gateway decisions with
status `executed`. Everything else is "not done" with the rule that fired, or "waiting for your approval".
"""

import hashlib
import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel

from app.agent.context import Profile, safe_label
from app.agent.tools import LEAK_DETAIL_LABELS, leak_subject
from app.audit import AuditLog
from app.engine.ads import campaign_prefix
from app.engine.products import margin_fact_id
from app.engine.scheduled import scheduled_prefix
from app.firewall.digit_check import check_output
from app.firewall.fact import Fact
from app.firewall.render import render
from app.firewall.store import FactStore
from app.gateway.store import Approval
from app.llm.adapter import LLMError
from app.llm.cache import ReplayMiss
from app.packs.leaks import biggest_leak, detector_labels
from app.services.finance import Computed

PROMPT_PATH = Path(__file__).resolve().parents[1] / "llm" / "prompts" / "brief_writer.md"
COMING_UP_DAYS = 14
COMING_UP_MAX = 5
MAX_OUTPUT_TOKENS = 900
REPROMPTS = 1

# Why the gateway (or the overnight job) did not run a reminder, in the owner's words. Unknown rules fall back to
# the rule name with underscores replaced, which is digit-free by construction.
RULE_WORDS = {
    "no_standing_mandate": "no signed reminder limit yet",
    "over_policy_cap": "above the reminder limit",
    "over_mandate_cap": "above your signed reminder limit",
    "not_allowlisted:customer_id": "customer is not on your reminder list",
    "frequency_cap": "already reminded in the last few days",
    "untrusted_source": "due date came from an unverified document",
    "tier_T3": "needs your signature",
}


def rule_words(rule: str | None) -> str:
    if not rule:
        return "not done"
    if rule.startswith("untrusted_provenance"):
        return "uses details from an unverified document"
    return RULE_WORDS.get(rule, safe_label(rule.replace("_", " ").replace(":", " ")))


def tool_words(tool: str) -> str:
    return safe_label(tool.replace("_", " "))


class ReminderOutcome(BaseModel):
    """One overdue invoice the overnight job looked at, and what the gateway decided."""

    scheduled_item_id: str
    invoice_id: str
    customer_id: str | None
    status: Literal["executed", "pending_approval", "denied", "skipped"]
    rule: str | None = None
    approval_id: str | None = None
    mandate_id: int | None = None
    tool: str = "send_invoice_reminder"  # "send_email" when the reminder was drafted for the owner to sign


class DoneItem(BaseModel):
    tool: str
    status: Literal["executed", "pending_approval", "denied", "skipped"]
    rule: str | None = None
    summary: str  # may contain {fact:id}
    amount: Fact | None = None
    date: Fact


class EmailPreview(BaseModel):
    """A drafted email waiting for the owner's signature: who it goes to and its subject. The full text, with every
    number traced to a fact, is on the approval sheet."""

    recipient: str
    subject: str


class NeedsYouItem(BaseModel):
    approval_id: str
    tool: str
    summary: str
    reasons: list[str]
    email: EmailPreview | None = None


class ComingUpItem(BaseModel):
    id: str
    kind: Literal["payable", "receivable"]
    label: str
    amount: Fact
    due: Fact


class ImproveItem(BaseModel):
    leak_id: str
    detector: str
    title: str
    about: str | None = None
    text: str  # may contain {fact:id}
    yearly_saving: Fact
    facts: dict[str, Fact]


class ProductLine(BaseModel):
    product_id: str
    name: str
    margin: Fact | None = None
    days_of_cover: Fact | None = None


class ProductBrief(BaseModel):
    best_margin: ProductLine | None = None
    worst_margin: ProductLine | None = None
    slow_movers: list[ProductLine] = []
    stockout_risk: list[ProductLine] = []


class CampaignLine(BaseModel):
    campaign_id: str
    campaign: str
    channel: str
    spend: Fact
    attributed_sales: Fact | None = None
    roas: Fact | None = None


class AdBrief(BaseModel):
    total_spend: Fact
    losing: list[CampaignLine] = []
    best_channel: str | None = None
    best_channel_roas: Fact | None = None


class BriefFirewall(BaseModel):
    attempts: int
    rejected: list[list[str]]
    fallback: bool


class MorningBrief(BaseModel):
    """What the Today screen renders. Prose carries {fact:id} placeholders resolved from `facts` (invariant 4)."""

    business_id: str
    as_of: Fact
    generated_by: Literal["llm", "template"]
    paragraphs: list[str]
    facts: dict[str, Fact]
    done_overnight: list[DoneItem]
    not_done: list[DoneItem]
    needs_you: list[NeedsYouItem]
    coming_up: list[ComingUpItem]
    improve: ImproveItem | None
    firewall: BriefFirewall
    products: ProductBrief | None = None
    ads: AdBrief | None = None
    could_also_check: list[str] = []


class _Cite:
    """Collects the facts the bundle cites. Only these may appear in the brief (the firewall checks)."""

    def __init__(self, pool: FactStore):
        self.pool = pool
        self.store = FactStore()

    def __call__(self, fact_id: str) -> str | None:
        if fact_id not in self.pool:
            return None
        self.store.add(self.pool.get(fact_id))
        return "{fact:" + fact_id + "}"

    def fact(self, fact_id: str) -> Fact | None:
        return self.pool.get(fact_id) if fact_id in self.pool else None


def _compact(d: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in d.items() if v not in (None, [], {})}


def _shortfall(store: FactStore, horizon: str = "30d") -> str:
    fact_id = f"forecast.{horizon}.min_balance"
    value = store.get(fact_id).value if fact_id in store else None
    return "expected" if isinstance(value, int) and value < 0 else "none"


def build(computed: Computed, profile: Profile, today: date, reminders: list[ReminderOutcome],
          pending: list[Approval], emails: dict[str, dict] | None = None) -> tuple[dict[str, Any], MorningBrief]:
    """The LLM's input bundle and a brief skeleton (structured sections, template paragraphs), from code only."""
    cite = _Cite(computed.store)
    names = profile.counterparty_names
    scheduled = {s.id: s for s in computed.inputs.scheduled}
    as_of = computed.store.get("clock.today")
    cite("clock.today")

    def who(cid: str | None) -> str:
        return names.get(cid or "", "a customer")

    executed, not_done = [], []
    done_items, not_done_items = [], []
    for r in reminders:
        amount_id = f"{scheduled_prefix(r.scheduled_item_id)}.amount"
        amount = cite(amount_id)
        entry = _compact({"action": "send_invoice_reminder", "customer": who(r.customer_id), "invoice_amount": amount})
        if r.status == "executed":
            executed.append(entry)
            summary = f"Reminder sent to {who(r.customer_id)}" + (f" for {amount}" if amount else "")
            done_items.append(DoneItem(tool="send_invoice_reminder", status="executed", summary=summary,
                                       amount=cite.fact(amount_id), date=as_of))
        else:
            why = rule_words(r.rule if r.status != "pending_approval" else "tier_T3")
            status = "waiting_for_approval" if r.status == "pending_approval" else "not_sent"
            not_done.append({**entry, "status": status, "why": why})
            summary = f"Reminder to {who(r.customer_id)} not sent: {why}"
            not_done_items.append(DoneItem(tool=r.tool, status=r.status, rule=r.rule,
                                           summary=summary, amount=cite.fact(amount_id), date=as_of))

    needs_you, needs_items = [], []
    for a in pending:
        party = next((names[v] for v in a.args.values() if isinstance(v, str) and v in names), None)
        summary = tool_words(a.tool) + (f" for {party}" if party else "")
        needs_you.append({"action": a.tool, "for": party, "why": rule_words(a.reasons[0] if a.reasons else None)})
        mail = (emails or {}).get(a.id)
        preview = EmailPreview(recipient=mail["recipient_name"], subject=mail["subject"]) if mail else None
        needs_items.append(NeedsYouItem(approval_id=a.id, tool=a.tool, summary=summary, reasons=a.reasons,
                                        email=preview))

    coming, coming_items = [], []
    horizon = today + timedelta(days=COMING_UP_DAYS)
    for s in sorted(scheduled.values(), key=lambda s: (s.due_date, s.id)):
        if s.status != "open" or not (today <= s.due_date <= horizon) or len(coming) >= COMING_UP_MAX:
            continue
        p = scheduled_prefix(s.id)
        spec = computed.inputs.pack.categories.get(s.category)
        label = safe_label(spec.label if spec else s.category.replace("_", " "))
        amount, due = cite(f"{p}.amount"), cite(f"{p}.due_date")
        if not (amount and due):
            continue
        party = names.get(s.counterparty_id or "")
        coming.append(_compact({"what": label, "who": party, "direction": "money_in" if s.kind == "receivable"
                                else "money_out", "amount": amount, "due": due}))
        coming_items.append(ComingUpItem(id=s.id, kind=s.kind, label=label + (f", {party}" if party else ""),
                                         amount=computed.store.get(f"{p}.amount"),
                                         due=computed.store.get(f"{p}.due_date")))

    leak = biggest_leak(list(computed.leaks))
    improve_bundle, improve = None, None
    if leak is not None:
        title = detector_labels(computed.inputs.pack).get(leak.detector, leak.detector.replace("_", " "))
        about = leak_subject(leak, computed.inputs.products, names)
        impact = cite(leak.impact.id)
        details = {safe_label(LEAK_DETAIL_LABELS.get(d.id.rsplit(".", 1)[1], d.id.rsplit(".", 1)[1])): cite(d.id)
                   for d in leak.details}
        improve_bundle = _compact({"finding": safe_label(title), "about": about, "yearly_impact": impact,
                                   "details": details})
        text = f"{safe_label(title)}" + (f" ({about})" if about else "") + f": about {impact}."
        improve = ImproveItem(leak_id=leak.id, detector=leak.detector, title=safe_label(title), about=about,
                              text=text, yearly_saving=leak.impact,
                              facts={f.id: f for f in leak.facts()})

    cash = _compact({"balance": cite("cash.balance"), "runway": cite("runway.days"),
                     "buffer": cite("cash.buffer_days"), "shortfall_next_30_days": _shortfall(computed.store)})
    bundle = {
        "business_name": profile.business_name,
        "today": cite("clock.today"),
        "cash": cash,
        "executed_actions": executed,
        "not_done_overnight": not_done,
        "pending_approvals": needs_you,
        "risks": [],
        "coming_up": coming,
        "biggest_leak": improve_bundle,
    }
    paragraphs = template_paragraphs(bundle)
    brief = MorningBrief(
        business_id=computed.inputs.info.id, as_of=as_of, generated_by="template", paragraphs=paragraphs,
        facts={f.id: f for f in cite.store}, done_overnight=done_items, not_done=not_done_items,
        needs_you=needs_items, coming_up=coming_items, improve=improve,
        firewall=BriefFirewall(attempts=0, rejected=[], fallback=True),
    )
    return bundle, brief


def product_brief(computed: Computed) -> ProductBrief | None:
    """Best and worst margins, slow movers and stock about to run out, from the engine's product facts."""
    insights, store = computed.products, computed.store
    names = {p.id: safe_label(p.name) for p in computed.inputs.products}
    margin_ids = {p.id: margin_fact_id(p.id) for p in computed.inputs.products}

    def line(pid: str | None) -> ProductLine | None:
        if pid is None:
            return None
        get = lambda fid: store.get(fid) if fid and fid in store else None  # noqa: E731
        return ProductLine(product_id=pid, name=names.get(pid, safe_label(pid)), margin=get(margin_ids.get(pid)),
                           days_of_cover=get(insights.cover_fact.get(pid)))

    brief = ProductBrief(best_margin=line(insights.best_margin), worst_margin=line(insights.worst_margin),
                         slow_movers=[line(p) for p in insights.slow_movers[:5]],
                         stockout_risk=[line(p) for p in insights.stockout_risk[:5]])
    empty = not (brief.best_margin or brief.worst_margin or brief.slow_movers or brief.stockout_risk)
    return None if empty else brief


def ad_brief(computed: Computed) -> AdBrief | None:
    """Campaigns whose attributed sales are below their spend, and the channel with the best return."""
    ads, store = computed.ads, computed.store
    if not ads.campaigns or "ads.total_spend" not in store:
        return None
    get = lambda fid: store.get(fid) if fid in store else None  # noqa: E731
    by_id = {c.id: c for c in ads.campaigns}
    losing = []
    for cid in ads.losing:
        c, pre = by_id[cid], campaign_prefix(cid)
        losing.append(CampaignLine(campaign_id=cid, campaign=safe_label(c.name), channel=safe_label(c.channel),
                                   spend=store.get(f"{pre}.spend"), attributed_sales=get(f"{pre}.attributed_sales"),
                                   roas=get(f"{pre}.roas")))
    return AdBrief(total_spend=store.get("ads.total_spend"), losing=losing,
                   best_channel=safe_label(ads.best_channel) if ads.best_channel else None,
                   best_channel_roas=get(ads.channel_fact.get(ads.best_channel, "")) if ads.best_channel else None)


def _section_facts(brief: MorningBrief) -> dict[str, Fact]:
    facts: dict[str, Fact] = {}
    if brief.products:
        p = brief.products
        for line in [p.best_margin, p.worst_margin, *p.slow_movers, *p.stockout_risk]:
            for fact in (line.margin, line.days_of_cover) if line else ():
                if fact is not None:
                    facts[fact.id] = fact
    if brief.ads:
        facts[brief.ads.total_spend.id] = brief.ads.total_spend
        for c in brief.ads.losing:
            for fact in (c.spend, c.attributed_sales, c.roas):
                if fact is not None:
                    facts[fact.id] = fact
        if brief.ads.best_channel_roas:
            facts[brief.ads.best_channel_roas.id] = brief.ads.best_channel_roas
    return facts


def template_paragraphs(b: dict[str, Any]) -> list[str]:
    """The brief in fixed sentences from the bundle: placeholders and names only, so it always passes."""
    out = []
    cash = b["cash"]
    line = f"Cash on hand is {cash['balance']}." if cash.get("balance") else "Cash position is not available yet."
    if cash.get("runway"):
        line += f" Runway: {cash['runway']}."
    if cash.get("shortfall_next_30_days") == "expected":
        line += " A shortfall is expected within the month."
    out.append(line)
    needs = [f"{tool_words(n['action'])}" + (f" for {n['for']}" if n.get("for") else "")
             for n in b["pending_approvals"]]
    needs += [f"reminder to {n['customer']} ({n['why']})" for n in b["not_done_overnight"]
              if n["why"] != RULE_WORDS["frequency_cap"] and n.get("status") != "waiting_for_approval"]
    if needs:
        out.append("Needs you today: " + "; ".join(needs) + ".")
    done = [f"reminder sent to {e['customer']}" + (f" for {e['invoice_amount']}" if e.get("invoice_amount") else "")
            for e in b["executed_actions"]]
    if done:
        out.append("Done overnight under your signed limits: " + "; ".join(done) + ".")
    coming = [f"{c['what']}" + (f" ({c['who']})" if c.get("who") else "") + f", {c['amount']} due {c['due']}"
              for c in b["coming_up"]]
    if coming:
        out.append("Coming up: " + "; ".join(coming) + ".")
    leak = b.get("biggest_leak")
    if leak:
        out.append(f"One thing to improve: {leak['finding']}" + (f" ({leak['about']})" if leak.get("about") else "")
                   + f", about {leak['yearly_impact']}.")
    return out


def system_prompt(profile: Profile) -> str:
    text = PROMPT_PATH.read_text(encoding="utf-8")
    text = text.split("-->", 1)[1] if "-->" in text else text
    return text.replace("{{business_name}}", profile.business_name).strip()


def _paragraphs(text: str) -> list[str]:
    return [p.strip() for p in text.replace("\r\n", "\n").split("\n\n") if p.strip()]


def write(llm: Any, computed: Computed, profile: Profile, today: date, reminders: list[ReminderOutcome],
          pending: list[Approval], audit: AuditLog, could_also_check: list[str] = (),
          emails: dict[str, dict] | None = None) -> MorningBrief:
    """Build the bundle, ask the brief writer, firewall the draft (one re-prompt), else use the template.
    `emails`: approval ID -> email view (recipient and subject) for the drafted emails waiting for a signature."""
    bundle, brief = build(computed, profile, today, reminders, pending, emails)
    brief = brief.model_copy(update={"products": product_brief(computed), "ads": ad_brief(computed),
                                     "could_also_check": list(could_also_check)})
    brief = brief.model_copy(update={"facts": {**brief.facts, **_section_facts(brief)}})
    known = FactStore()
    known.add_all(brief.facts.values())
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system_prompt(profile)},
        {"role": "user", "content": json.dumps(bundle, sort_keys=True)},
    ]
    attempts, rejected, text = 0, [], None
    unavailable = False
    for _ in range(1 + REPROMPTS):
        try:
            result = llm.chat("brief_writer", messages, max_output_tokens=MAX_OUTPUT_TOKENS)
        except (LLMError, ReplayMiss):
            unavailable = True
            break
        attempts += 1
        draft = (result.content or "").strip()
        check = check_output(draft, known)
        if draft and check.ok:
            text = draft
            break
        kinds = sorted({v.kind.value for v in check.violations}) or ["empty"]
        rejected.append(kinds)
        audit.append("brief.firewall_rejected", {"business_id": brief.business_id, "draft": attempts,
                                                 "violations": kinds})
        messages += [{"role": "assistant", "content": draft},
                     {"role": "user", "content": "[Numeric Firewall] Rejected: write every number and date only "
                      "as a {fact:<id>} placeholder from the input, and cite no other fact IDs. Rewrite it."}]

    if text is not None:
        render(text, known)  # re-checks the firewall: there is no path around it
        brief = brief.model_copy(update={"generated_by": "llm", "paragraphs": _paragraphs(text)})
    for p in brief.paragraphs + brief.could_also_check:
        render(p, known)
    brief = brief.model_copy(update={"firewall": BriefFirewall(attempts=attempts, rejected=rejected,
                                                               fallback=text is None)})
    audit.append("brief.generated", {
        "business_id": brief.business_id, "as_of": today.isoformat(), "generated_by": brief.generated_by,
        "llm_unavailable": unavailable, "drafts": attempts, "rejected": rejected,
        "fact_ids": sorted(brief.facts), "executed_actions": len(bundle["executed_actions"]),
        "bundle_sha256": hashlib.sha256(json.dumps(bundle, sort_keys=True).encode()).hexdigest(),
    })
    return brief


# Storage: one JSON file per business and day under the tenant's directory; the latest is what Today shows.

def save(tenant_dir: Path, brief: MorningBrief) -> Path:
    folder = tenant_dir / "briefs"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{brief.as_of.value.isoformat()}.json"
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(brief.model_dump_json(), encoding="utf-8")
    tmp.replace(path)
    return path


def latest(tenant_dir: Path) -> MorningBrief | None:
    files = sorted((tenant_dir / "briefs").glob("*.json"))
    return MorningBrief.model_validate_json(files[-1].read_text(encoding="utf-8")) if files else None
