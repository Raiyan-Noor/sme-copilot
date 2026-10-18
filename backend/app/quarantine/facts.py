"""Facts for an inbox item's amount, due date and received date (invariant 4).

The values are untrusted (read from the email by the extractor); the fact's source row is the inbox item itself,
and the planner marks these fact IDs untrusted (invariant 3) whenever it is handed one.
"""

from app.engine.common import a_date, money, slug
from app.firewall.fact import Fact
from app.quarantine.store import InboxRecord

BY = "quarantine.inbox"


def inbox_prefix(email_id: str) -> str:
    return f"inbox.{slug(email_id)}"


def record_facts(record: InboxRecord, currency: str) -> list[Fact]:
    p = inbox_prefix(record.email_id)
    src = [f"inbox:{record.email_id}"]
    f = record.fields
    out = []
    if f.amount_minor:
        out.append(money(f"{p}.amount", f.amount_minor.value, currency, BY, src))
    if f.due_date:
        out.append(a_date(f"{p}.due_date", f.due_date.value, BY, src))
    if record.received_on:
        out.append(a_date(f"{p}.received", record.received_on, BY, src))
    return out
