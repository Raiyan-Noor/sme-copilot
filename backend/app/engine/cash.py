"""Cash balance and buffer days. Pure: (snapshot, pack, clock) -> list[Fact].

Balance per account comes from the statement's own running balance where there is one: the last row with a
balance, plus any later rows without one. The fact cites only those rows, so the trace is short and checkable
against the statement. An account whose statement has no balance column is summed from its rows (opening zero).
"""

from collections import defaultdict

from app.clock import Clock
from app.engine.common import a_date, days, in_window, line_of, money, slug, window
from app.engine.pack_inputs import EnginePack
from app.firewall.fact import Fact
from app.ledger.snapshot import LedgerSnapshot, Transaction

BY_BALANCE = "engine.cash.cash_balance"
BY_BUFFER = "engine.cash.buffer_days"

# Every real cash outflow counts against the buffer, whatever its P&L line (a refund in a revenue category is still
# money leaving). Only moves between own accounts, owner drawings and opening balances are left out.
NOT_SPEND_LINES = frozenset({"transfer", "owner", "opening"})


def _account_balance(rows: list[Transaction]) -> tuple[int, list[str]]:
    """(balance, cited row IDs) for one account's rows in statement order."""
    anchor = max((i for i, t in enumerate(rows) if t.balance_minor is not None), default=None)
    if anchor is None:
        return sum(t.amount_minor for t in rows), [t.id for t in rows]
    tail = rows[anchor + 1:]
    return rows[anchor].balance_minor + sum(t.amount_minor for t in tail), [rows[anchor].id] + [t.id for t in tail]


def cash_balance(snapshot: LedgerSnapshot, clock: Clock) -> list[Fact]:
    """`cash.balance` (all accounts), `cash.balance.<account_id>` and `cash.last_activity` as of today."""
    today = clock.today()
    by_account: dict[str, list[Transaction]] = defaultdict(list)
    for t in snapshot.transactions:  # snapshot order is statement order
        if t.posted_on <= today:
            by_account[t.account_id].append(t)
    facts: list[Fact] = []
    total, cited = 0, []
    for account in sorted(by_account):
        bal, ids = _account_balance(by_account[account])
        total += bal
        cited += ids
        facts.append(money(f"cash.balance.{slug(account)}", bal, snapshot.currency, BY_BALANCE, ids))
    if not by_account:
        return [money("cash.balance", 0, snapshot.currency, BY_BALANCE, ["clock:today"])]
    last = max(t.posted_on for rows in by_account.values() for t in rows)
    last_ids = [t.id for rows in by_account.values() for t in rows if t.posted_on == last]
    return [
        money("cash.balance", total, snapshot.currency, BY_BALANCE, cited, inputs=[f.id for f in facts]),
        *facts,
        a_date("cash.last_activity", last, BY_BALANCE, last_ids),
    ]


def buffer_days(snapshot: LedgerSnapshot, pack: EnginePack, clock: Clock, window_days: int = 90) -> list[Fact]:
    """How many days today's cash covers at the recent average daily spend.

    Average daily spend = all outflows over the last `window_days` complete days, divided by `window_days`, except
    owner drawings, transfers between own accounts and opening balances.
    """
    balance = cash_balance(snapshot, clock)[0]
    start, end = window(clock.today(), window_days)
    spend = [t for t in in_window(snapshot, start, end)
             if t.amount_minor < 0 and line_of(t, pack) not in NOT_SPEND_LINES]
    ids = [t.id for t in spend]
    avg = round(-sum(t.amount_minor for t in spend) / window_days)
    avg_id = f"cash.avg_daily_spend.last_{window_days}d"
    buffer = max(0.0, balance.value / avg) if avg > 0 else None
    return [
        money(avg_id, avg, snapshot.currency, BY_BUFFER, ids or ["clock:today"]),
        days("cash.buffer_days", buffer, BY_BUFFER, inputs=["cash.balance", avg_id],
             none_display="no recent spending"),
    ]
