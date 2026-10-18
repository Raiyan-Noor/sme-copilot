"""Inbox Sentinel checks over one quarantined email. Pure code over code-parsed headers, typed fields and the
business's own records; no LLM decides a flag on its own.

Flags (codes match manifest.json's flag_vocabulary):
- lookalike_domain      From or Reply-To imitates a known domain (domains.py)
- display_name_spoof    display name is the owner or a known contact, address is not theirs
- reply_to_mismatch     Reply-To domain differs from From domain
- bank_detail_change    a known payee, but the account to pay is not one on file (or the message asks to change it)
- first_time_payee      payment requested to an account/payee the business has never paid  -> hold
- amount_anomaly        amount far outside the payee's history (or, for a new payee, the business's)
- urgency               pressure to act fast, skip a call-back or keep it secret (code patterns OR the model)
- instruction_like_text text aimed at an AI agent (code patterns OR the model)
- hidden_text           text a human cannot see (PDF render mode 3 / white / tiny, HTML hidden styles)
- receipt_total_mismatch receipt lines, or cash minus change, do not add up to the stated total
- duplicate_invoice     invoice number already received, or a ledger invoice re-sent as overdue before it is due
- amount_mismatch       amount differs from the ledger record of the same invoice

Invariant 3: whatever the flags say, values from the email stay untrusted, so any action built on them is Tier 3.
`hold` additionally tells the agent and the owner not to pay until the call-back script is done.
"""

from dataclasses import dataclass
from datetime import date
from typing import Literal

from pydantic import BaseModel
from rapidfuzz import fuzz

from app.ledger.money import format_minor
from app.quarantine.typed import DocumentFields, OwnerView
from app.sentinel.directory import Counterparty, Directory
from app.sentinel.domains import find_lookalike

FlagCode = Literal[
    "lookalike_domain", "display_name_spoof", "reply_to_mismatch", "bank_detail_change", "first_time_payee",
    "amount_anomaly", "urgency", "instruction_like_text", "hidden_text", "receipt_total_mismatch",
    "duplicate_invoice", "amount_mismatch",
]
Severity = Literal["high", "medium"]
Risk = Literal["none", "review", "hold"]
SenderStatus = Literal["known", "own_business", "lookalike", "unknown"]
Recommendation = Literal[
    "verify_by_phone_before_paying", "do_not_pay_duplicate", "check_amount_against_ledger",
    "reimburse_line_items_only", "treat_embedded_text_as_data", "owner_review",
]

SEVERITY: dict[str, Severity] = {
    "lookalike_domain": "high", "display_name_spoof": "high", "bank_detail_change": "high",
    "first_time_payee": "high", "instruction_like_text": "high", "hidden_text": "high",
    "receipt_total_mismatch": "high", "duplicate_invoice": "high",
    "reply_to_mismatch": "medium", "amount_anomaly": "medium", "urgency": "medium", "amount_mismatch": "medium",
}
PAYMENT_CATEGORIES = {"invoice", "payment_request", "bank_detail_change", "overdue_notice"}
PAYABLE_KINDS = {"supplier", "payee", "staff"}
NAME_MATCH = 90
ANOMALY_VS_MAX = 1.5  # known payee: above 1.5x the largest payment ever made to them
ANOMALY_VS_TYPICAL = 10  # new payee: above 10x the business's median outgoing payment
MIN_HISTORY = 3
# The model's instruction categories that mean "aimed at an AI/system". A plain payment request addressed to a person
# ("payment_or_approval_request") is fraud's normal shape, judged by the other checks, not instruction-like text.
AI_DIRECTED = {"ignore_instructions", "claims_owner_authority", "data_exfiltration", "mandate_or_policy_change"}


class Flag(BaseModel):
    code: FlagCode
    severity: Severity
    detected_by: list[Literal["code", "model"]]
    evidence: dict[str, str | int | bool | None] = {}  # owner-facing: domains, masked accounts, refs, amounts


class CallScript(BaseModel):
    """A verification call the owner makes on a number from their own records. Generated in code, not by an LLM."""

    call: str
    number_source: str
    lines: list[str]


class SentinelReport(BaseModel):
    sender_status: SenderStatus
    sender_counterparty_id: str | None = None
    claimed_counterparty_id: str | None = None
    payee_counterparty_id: str | None = None
    payment_requested: bool = False
    flags: list[Flag] = []
    risk: Risk = "none"
    hold: bool = False
    recommended: list[Recommendation] = []
    call_script: CallScript | None = None

    @property
    def codes(self) -> list[str]:
        return [f.code for f in self.flags]


@dataclass(frozen=True)
class Headers:
    """Code-parsed header facts (quarantine/mime.py); never the model's reading of them."""

    from_address: str
    from_display_name: str
    from_domain: str
    reply_to_domain: str | None
    sent_on: date | None


@dataclass(frozen=True)
class LedgerInvoice:
    reference: str
    amount_minor: int
    due_date: date
    counterparty_id: str | None


@dataclass(frozen=True)
class TextEvidence:
    """Code-side text signals (quarantine/signals.py) and hidden-text findings, by name only."""

    instruction_patterns: tuple[str, ...] = ()
    urgency_patterns: tuple[str, ...] = ()
    hidden_reasons: tuple[str, ...] = ()


def _name_match(display: str, cp: Counterparty) -> bool:
    d = display.casefold().strip()
    if not d:
        return False
    names = [cp.name, *cp.person_names]
    return any(fuzz.token_set_ratio(d, n.casefold()) >= NAME_MATCH for n in names if n)


def _resolve_sender(h: Headers, d: Directory) -> tuple[SenderStatus, Counterparty | None, str | None]:
    addr, dom = h.from_address.lower(), h.from_domain.lower()
    if dom == d.own_domain:
        cp = next((c for c in d.counterparties.values() if addr in c.emails), None)
        return "own_business", cp, None
    cp = d.by_domain(dom)
    if cp:
        return "known", cp, None
    look = find_lookalike(dom, d.known_domains)
    if look:
        return "lookalike", d.by_domain(look.imitates), look.imitates
    return "unknown", None, None


def _mask(last4: str | None) -> str | None:
    return f"ending {last4}" if last4 else None


def assess(h: Headers, f: DocumentFields, owner: OwnerView, text: TextEvidence, d: Directory, currency: str,
           ledger: dict[str, LedgerInvoice], seen_invoices: dict[str, str], email_id: str) -> SentinelReport:
    flags: dict[str, Flag] = {}

    def flag(code: FlagCode, by: str = "code", **evidence):
        if code in flags:
            if by not in flags[code].detected_by:
                flags[code].detected_by.append(by)
            flags[code].evidence.update({k: v for k, v in evidence.items() if v is not None})
            return
        flags[code] = Flag(code=code, severity=SEVERITY[code], detected_by=[by],
                           evidence={k: v for k, v in evidence.items() if v is not None})

    status, sender_cp, imitated = _resolve_sender(h, d)
    if imitated:
        flag("lookalike_domain", sender_domain=h.from_domain, imitates=imitated)
    if h.reply_to_domain and h.reply_to_domain != h.from_domain:
        flag("reply_to_mismatch", from_domain=h.from_domain, reply_to_domain=h.reply_to_domain)
        if (look := find_lookalike(h.reply_to_domain, d.known_domains)) is not None:
            flag("lookalike_domain", reply_to_domain=h.reply_to_domain, imitates=look.imitates)

    # Display name claims to be someone the business knows, from an address that is not theirs.
    claimed = sender_cp
    for cp in d.counterparties.values():
        if _name_match(h.from_display_name, cp) and h.from_domain not in cp.domains \
                and h.from_address.lower() not in cp.emails:
            flag("display_name_spoof", display_name_matches=cp.id, from_domain=h.from_domain)
            claimed = claimed or cp
            break

    # Who would be paid, and whether the business has ever paid that account.
    payment = f.category in PAYMENT_CATEGORIES or f.has_invoice_document or f.payee_account_token is not None
    token = f.payee_account_token.value if f.payee_account_token else None
    payee = d.by_account(token) if token else None
    if payee is None and claimed is not None and claimed.kind in PAYABLE_KINDS:
        payee = claimed
    amount = f.amount_minor.value if f.amount_minor else None

    if payee is not None and payment and token and payee.account_tokens and token not in payee.account_tokens:
        flag("bank_detail_change", payee=payee.id, account_on_file=_mask(payee.account_last4[0]),
             account_in_message=_mask(f.payee_account_last4))
    if f.asks_to_change_bank_details or f.category == "bank_detail_change":
        flag("bank_detail_change", "model", payee=payee.id if payee else None,
             account_in_message=_mask(f.payee_account_last4))

    history = d.history_for(payee) if payee else (d.payments_by_token.get(token, []) if token else [])
    if payment and payee is None and not history and (amount is not None or token is not None):
        flag("first_time_payee", account_in_message=_mask(f.payee_account_last4), sender_domain=h.from_domain)

    if payment and amount is not None:
        if payee is not None and len(history) >= MIN_HISTORY and amount > ANOMALY_VS_MAX * max(history):
            flag("amount_anomaly", amount=format_minor(amount, currency),
                 largest_previous=format_minor(max(history), currency))
        elif payee is None and not history and d.typical_payment_minor and \
                amount > ANOMALY_VS_TYPICAL * d.typical_payment_minor:
            flag("amount_anomaly", amount=format_minor(amount, currency),
                 typical_payment=format_minor(d.typical_payment_minor, currency))

    if text.urgency_patterns:
        flag("urgency", patterns=",".join(text.urgency_patterns))
    if f.model_urgency or f.model_secrecy:
        flag("urgency", "model")
    if text.instruction_patterns:
        flag("instruction_like_text", patterns=",".join(text.instruction_patterns))
    if f.model_instruction_flag and f.model_instruction_category in AI_DIRECTED:
        flag("instruction_like_text", "model", category=f.model_instruction_category)
    if text.hidden_reasons:
        flag("hidden_text", how=",".join(sorted(set(text.hidden_reasons))))

    if f.has_receipt:
        total, items = f.stated_total_minor, f.line_items_sum_minor
        paid = (f.cash_tendered_minor - f.change_minor
                if f.cash_tendered_minor and f.change_minor is not None and f.cash_tendered_minor >= f.change_minor
                else None)
        if total is not None and items is not None and items != total:
            flag("receipt_total_mismatch", stated_total=format_minor(total, currency),
                 line_items_sum=format_minor(items, currency))
        if total is not None and paid is not None and paid != total:
            flag("receipt_total_mismatch", cash_minus_change=format_minor(paid, currency))
        if f.model_totals_mismatch:
            flag("receipt_total_mismatch", "model")

    number = f.invoice_number.value if f.invoice_number else None
    if number and (f.invoice_number_from_document or f.category in ("invoice", "overdue_notice")):
        record = ledger.get(number)
        earlier = seen_invoices.get(number)
        if earlier and earlier != email_id:
            flag("duplicate_invoice", invoice_number=number, first_received_in=earlier)
        if record and (f.marked_overdue or f.category == "overdue_notice") and h.sent_on and \
                record.due_date > h.sent_on:
            flag("duplicate_invoice", invoice_number=number, ledger_due_date=record.due_date.isoformat())
        amounts = {a for a in (amount, f.email_amount_minor.value if f.email_amount_minor else None) if a}
        if record and amounts and any(a != record.amount_minor for a in amounts):
            flag("amount_mismatch", invoice_number=number,
                 ledger_amount=format_minor(record.amount_minor, currency),
                 amount_in_message=format_minor(max(amounts), currency))
            if not earlier:  # a recorded invoice resent with a different amount is a duplicate claim
                flag("duplicate_invoice", invoice_number=number)

    ordered = sorted(flags.values(), key=lambda x: (x.severity != "high", x.code))
    high = any(x.severity == "high" for x in ordered)
    codes = {x.code for x in ordered}
    rec: list[Recommendation] = []
    if codes & {"bank_detail_change", "first_time_payee", "lookalike_domain", "display_name_spoof"}:
        rec.append("verify_by_phone_before_paying")
    if "duplicate_invoice" in codes:
        rec.append("do_not_pay_duplicate")
    if "amount_mismatch" in codes:
        rec.append("check_amount_against_ledger")
    if "receipt_total_mismatch" in codes:
        rec.append("reimburse_line_items_only")
    if codes & {"instruction_like_text", "hidden_text"}:
        rec.append("treat_embedded_text_as_data")
    if ordered and not rec:
        rec.append("owner_review")

    report = SentinelReport(
        sender_status=status,
        sender_counterparty_id=sender_cp.id if sender_cp and status in ("known", "own_business") else None,
        claimed_counterparty_id=claimed.id if claimed else None,
        payee_counterparty_id=payee.id if payee else None,
        payment_requested=payment,
        flags=ordered,
        risk="hold" if high else "review" if ordered else "none",
        hold=high and payment,
        recommended=rec,
    )
    if "verify_by_phone_before_paying" in rec:
        report.call_script = call_script(report, f, owner, d, currency, payee or claimed)
    return report


def call_script(report: SentinelReport, f: DocumentFields, owner: OwnerView, d: Directory, currency: str,
                who: Counterparty | None) -> CallScript:
    """The out-of-band verification call. Every contact detail comes from the business's own records."""
    name = who.name if who else (owner.payee_name or "the sender")
    lines = [
        "Do not use any phone number, link or contact detail from this message.",
        f"Call {name} on the number you already have on file (a past invoice, your contract, or their website "
        f"typed in yourself)." if who else
        "This payee is not in your records. Find their number independently before you pay anything.",
    ]
    if who is not None and who.kind == "owner":
        lines[1] = f"Call {who.name} directly on their usual number and ask whether they sent this request."
    lines.append("Ask them to read the details to you; do not read them out first.")
    if f.invoice_number:
        lines.append(f"Confirm the invoice number: {f.invoice_number.value}.")
    if f.amount_minor:
        lines.append(f"Confirm the amount: {format_minor(f.amount_minor.value, currency)}.")
    if f.payee_account_last4:
        on_file = f" Your records show {who.name}'s account ending {who.account_last4[0]}." \
            if who and who.account_last4 else ""
        lines.append(f"The message asks you to pay an account ending {f.payee_account_last4}.{on_file} "
                     f"Ask which account they want paid and whether it changed.")
    lines.append("If anything differs, or they did not send it, do not pay. Mark the message as fraud.")
    return CallScript(call=name, number_source="your own records, never the message", lines=lines)
