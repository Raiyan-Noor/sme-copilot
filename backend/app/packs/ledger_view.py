"""Pack-driven categorization of a LedgerSnapshot, and the DataFrame view detectors and KPIs read.

Categories depend on the pack, so the same ledger categorizes differently under a different pack. A category set
by ingestion is kept only if the active pack defines it; otherwise the pack's rules decide. Descriptions and
counterparties are untrusted text (invariant 2): they are read here to classify rows and never leave this module
except as category IDs and row IDs.
"""

import pandas as pd

from app.engine.pack_inputs import EnginePack, build_engine_pack
from app.ledger.snapshot import LedgerSnapshot, Transaction
from app.packs.schema import Category, Pack

UNCATEGORIZED = "uncategorized"
COLUMNS = ("row_id", "date", "amount_minor", "counterparty", "description", "category", "kind")


def _matches(cat: Category, t: Transaction) -> bool:
    if cat.match is None:
        return False
    direction = cat.direction
    if (direction == "in" and t.amount_minor <= 0) or (direction == "out" and t.amount_minor >= 0):
        return False
    if (t.channel or "").lower() in cat.match.channel:
        return True
    cp, desc = (t.counterparty or "").lower(), t.description.lower()
    return any(k in cp for k in cat.match.counterparty) or any(k in desc for k in cat.match.description)


def category_for(t: Transaction, pack: Pack) -> str:
    if t.category in pack.categories:
        return t.category
    return next((cid for cid, c in pack.categories.items() if _matches(c, t)), UNCATEGORIZED)


def categorize_snapshot(snapshot: LedgerSnapshot, pack: Pack) -> LedgerSnapshot:
    """Return the snapshot with every transaction's category set by this pack. The input is not modified."""
    txns = tuple(t.model_copy(update={"category": category_for(t, pack)}) for t in snapshot.transactions)
    return snapshot.model_copy(update={"transactions": txns})


def frame(snapshot: LedgerSnapshot, pack: Pack) -> pd.DataFrame:
    """Categorized rows as a DataFrame with COLUMNS. `kind` is the engine kind, or "uncategorized"."""
    engine: EnginePack = build_engine_pack(pack.engine_doc(), [])
    rows = []
    for t in snapshot.transactions:
        cat = category_for(t, pack)
        # Uncategorized rows get their own kind, so they never count as revenue or cost (same rule as the engine).
        kind = UNCATEGORIZED if cat == UNCATEGORIZED else engine.kind_of(cat, t.amount_minor)
        rows.append((t.id, t.posted_on, t.amount_minor, t.counterparty or "", t.description, cat, kind))
    df = pd.DataFrame(rows, columns=list(COLUMNS))
    df["date"] = pd.to_datetime(df["date"])
    df["amount_minor"] = df["amount_minor"].astype("int64")
    return df
