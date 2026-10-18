"""Facts for open scheduled items: issued customer invoices (receivables) and known bills (payables).

Pure: (scheduled items, clock, currency) -> list[Fact]. Gives each open item an amount, a due date and, once it is
past due, how many days overdue, so the planner can cite an invoice's amount by fact ID (invariant 4) and pass that
same fact to propose_action instead of writing a number.

IDs look like `scheduled.<item id>.amount`; the item ID is slugged to fit the fact ID grammar.
"""

from app.clock import Clock
from app.engine.common import CLOCK_SOURCE, a_date, days, money, slug
from app.firewall.fact import Fact
from app.ledger.scheduled import ScheduledItem

BY = "engine.scheduled.scheduled_item_facts"


def scheduled_prefix(item_id: str) -> str:
    return f"scheduled.{slug(item_id)}"


def scheduled_item_facts(items: tuple[ScheduledItem, ...], clock: Clock, currency: str) -> list[Fact]:
    """Amount, due date and (if past due) days overdue for every open item, in input order."""
    today = clock.today()
    facts: list[Fact] = []
    for item in items:
        if item.status != "open":
            continue
        prefix = scheduled_prefix(item.id)
        facts += [
            money(f"{prefix}.amount", item.amount_minor, currency, BY, [item.id]),
            a_date(f"{prefix}.due_date", item.due_date, BY, [item.id]),
        ]
        if item.due_date < today:
            facts.append(days(f"{prefix}.days_overdue", (today - item.due_date).days, BY, [item.id, CLOCK_SOURCE]))
    return facts
