"""Turn clean inbox items into forecast inputs: promises to pay, purchase orders and bill/invoice due dates.

Writes `scheduled_items` rows (the forecast's input; engine/forecast.py) with `source` = mailbox_promise |
mailbox_po | mailbox_invoice. Those sources are not in the planner's trusted set (agent/tools.py), so their amounts
and dates reach the planner as untrusted facts (invariant 3) and every forecast fact built on them lists the row in
its source rows.

Only items the sentinel passed (risk "none") from a known counterparty (or the business itself, for its own POs)
feed the forecast. A flagged email never moves the forecast. Items already in the ledger are matched, not added
again: same reference, or same counterparty, direction and amount within a few weeks.
"""

import sqlite3
from datetime import date, timedelta

from app.ledger.scheduled import ScheduledItem, load_scheduled
from app.quarantine.store import FeedOutcome
from app.quarantine.typed import DocumentFields
from app.sentinel.checks import SentinelReport
from app.sentinel.directory import Directory

PROMISE_SOURCE = "mailbox_promise"
PO_SOURCE = "mailbox_po"
INVOICE_SOURCE = "mailbox_invoice"
MATCH_WINDOW_DAYS = 45
BILL_MATCH_DAYS = 7


def _item_id(email_id: str, n: int) -> str:
    return f"MBX-{email_id.upper()}-{n}"


def _match(existing: tuple[ScheduledItem, ...], kind: str, amount: int, due: date, cp: str | None,
           window: int) -> ScheduledItem | None:
    for s in existing:
        if s.kind == kind and s.amount_minor == amount and abs((s.due_date - due).days) <= window \
                and (cp is None or s.counterparty_id == cp):
            return s
    return None


def plan_items(email_id: str, f: DocumentFields, report: SentinelReport, d: Directory,
               existing: tuple[ScheduledItem, ...], today: date) -> tuple[FeedOutcome, list[ScheduledItem]]:
    if report.risk != "none":
        return "held_by_sentinel", []
    cp_id = report.sender_counterparty_id if report.sender_status == "known" else None
    by_ref = {s.reference: s for s in existing if s.reference}

    if f.category == "promise_to_pay" and f.promises:
        if cp_id is None:
            return "counterparty_unknown", []
        refs = [r for r in ([f.invoice_number.value] if f.invoice_number else []) + list(f.referenced_invoice_numbers)
                if r in by_ref and by_ref[r].kind == "receivable"]
        original = by_ref[refs[0]] if refs else None
        items = []
        for n, p in enumerate(f.promises, start=1):
            amount = p.amount_minor.value if p.amount_minor else (
                original.amount_minor if original and len(f.promises) == 1 else None)
            if amount is None or p.date.value < today:
                continue
            items.append(ScheduledItem(
                id=_item_id(email_id, n), kind="receivable",
                category=original.category if original else d.category_by_counterparty.get(cp_id, "customer_invoice"),
                due_date=p.date.value, amount_minor=amount, counterparty_id=cp_id,
                reference=original.reference if original else None, source=PROMISE_SOURCE))
        return ("scheduled", items) if items else ("past_due", [])

    if f.category == "purchase_order" or f.po_number is not None:
        if f.amount_minor is None:
            return "missing_fields", []
        sender_kind = d.counterparties[cp_id].kind if cp_id and cp_id in d.counterparties else None
        incoming = f.po_direction == "incoming_from_customer" or (f.po_direction is None and sender_kind == "customer")
        kind = "receivable" if incoming else "payable"
        terms = (f.payment_terms_days.value if f.payment_terms_days
                 else d.counterparties[cp_id].terms_days if cp_id and cp_id in d.counterparties else None)
        due = f.due_date.value if f.due_date else (
            f.start_date.value + timedelta(days=terms or 0) if f.start_date else None)
        amount = f.amount_minor.value
        if report.sender_status == "own_business":  # our own PO to a supplier: match it, never guess the payee
            anchor = due or today
            return ("already_scheduled", []) if _match(existing, "payable", amount, anchor, None,
                                                       MATCH_WINDOW_DAYS) else ("counterparty_unknown", [])
        if cp_id is None:
            return "counterparty_unknown", []
        if due is None:
            return "missing_fields", []
        if _match(existing, kind, amount, due, cp_id, MATCH_WINDOW_DAYS):
            return "already_scheduled", []
        if due < today:
            return "past_due", []
        category = d.category_by_counterparty.get(cp_id) or ("customer_invoice" if incoming else None)
        if category is None:
            return "missing_fields", []
        return "scheduled", [ScheduledItem(
            id=_item_id(email_id, 1), kind=kind, category=category, due_date=due, amount_minor=amount,
            counterparty_id=cp_id, reference=f.po_number.value if f.po_number else None, source=PO_SOURCE)]

    if f.category in ("invoice", "payment_request", "overdue_notice") or f.has_invoice_document:
        if cp_id is None or d.counterparties[cp_id].kind not in ("supplier", "payee"):
            return "counterparty_unknown", []
        if f.amount_minor is None or f.due_date is None:
            return "missing_fields", []
        number = f.invoice_number.value if f.invoice_number else None
        amount, due = f.amount_minor.value, f.due_date.value
        if (number and number in by_ref) or _match(existing, "payable", amount, due, cp_id, BILL_MATCH_DAYS):
            return "already_scheduled", []
        if due < today:
            return "past_due", []
        category = d.category_by_counterparty.get(cp_id)
        if category is None:
            return "missing_fields", []
        return "scheduled", [ScheduledItem(
            id=_item_id(email_id, 1), kind="payable", category=category, due_date=due, amount_minor=amount,
            counterparty_id=cp_id, reference=number, source=INVOICE_SOURCE)]

    return "not_applicable", []


def write_items(conn: sqlite3.Connection, items: list[ScheduledItem]) -> None:
    with conn:
        conn.executemany(
            "INSERT OR IGNORE INTO scheduled_items (id, kind, category, due_date, amount_minor, status,"
            " counterparty_id, reference, source) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [(s.id, s.kind, s.category, s.due_date.isoformat(), s.amount_minor, s.status, s.counterparty_id,
              s.reference, s.source) for s in items])


def existing_items(conn: sqlite3.Connection) -> tuple[ScheduledItem, ...]:
    return load_scheduled(conn)
