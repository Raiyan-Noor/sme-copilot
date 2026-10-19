"""The business's own records uploaded at onboarding: products, per-product sales and ad spend (CSV).

Bank and wallet statements are not parsed here: they go through ledger/ingest.py like every statement. This module
covers the point-of-sale and marketing exports the engine reads next to the ledger (the same files a seeded
business has in its seed folder), so an onboarded business and a seeded one feed the engine the same way.

Rules, as for statements
- Headers are case-insensitive with common aliases (see the *_COLUMNS maps); unknown columns are dropped.
- Money becomes exact integer minor units (ledger/money.py); a bad amount is a row error, never rounded.
- All-or-nothing: any bad row rejects the file and RecordsError lists every bad line.
- Names (products, campaigns, channels) are validated short strings: letters, digits, spaces and a few punctuation
  marks, at most 60 characters. They are the owner's own labels, and the planner only ever sees them through
  agent.context.safe_label (invariant 2: no free text from a file reaches it).

`detect_kind` picks the kind from the header row, so one drop zone takes any of the four CSVs.
"""

import csv
import hashlib
import io
import re
from collections import Counter
from datetime import date, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.ledger.ingest import COLUMN_ALIASES as STATEMENT_COLUMNS
from app.ledger.ingest import RowError
from app.ledger.money import AmountError, parse_minor
from app.ledger.pos import Product, SaleLine

CsvKind = Literal["bank", "sales", "products", "ad_spend"]

PRODUCT_COLUMNS: dict[str, tuple[str, ...]] = {
    "id": ("sku", "id", "product_id", "item_code", "code"),
    "name": ("name", "product", "product_name", "item", "item_name", "title"),
    "category": ("category", "type", "product_category", "department"),
    "cost": ("cost", "cost_price", "unit_cost", "buy_price", "purchase_price"),
    "price": ("price", "sale_price", "selling_price", "retail_price", "unit_price", "mrp"),
    "stock": ("stock", "on_hand", "qty_on_hand", "stock_qty", "in_stock", "inventory", "quantity_in_stock"),
    "supplier": ("supplier", "supplier_id", "vendor"),
}
SALES_COLUMNS: dict[str, tuple[str, ...]] = {
    "date": ("date", "sale_date", "order_date", "day"),
    "product": ("sku", "product_id", "product", "item", "item_code", "product_name"),
    "qty": ("qty", "quantity", "units", "units_sold"),
    "revenue": ("revenue", "amount", "total", "sales", "net_sales", "line_total"),
    "unit_price": ("unit_price", "price", "selling_price"),
}
AD_COLUMNS: dict[str, tuple[str, ...]] = {
    "date": ("date", "day", "week", "week_start", "month", "reporting_starts"),
    "campaign": ("campaign", "campaign_name", "ad_set", "ad_name"),
    "channel": ("channel", "platform", "network", "source"),
    "spend": ("spend", "amount_spent", "cost", "ad_spend", "spent"),
    "attributed_sales": ("attributed_sales", "sales", "revenue", "conversion_value", "purchases_value",
                         "purchase_value"),
    "product": ("product", "sku", "product_id"),
}

NAME = re.compile(r"^[\w][\w &'.,/+()\-]{0,59}$", re.UNICODE)
SLUG = re.compile(r"[^A-Z0-9]+")
DATE_FORMATS = ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%d.%m.%Y")
MAX_ROWS = 20_000


class RecordsError(ValueError):
    """The file was rejected; nothing was written."""

    def __init__(self, errors: list[RowError]):
        self.errors = errors
        shown = "; ".join(f"line {e.line}: {e.message}" for e in errors[:5])
        more = f" (+{len(errors) - 5} more)" if len(errors) > 5 else ""
        super().__init__(f"file rejected: {shown}{more}")


class AdSpendLine(BaseModel):
    """Spend on one campaign for one day (or week, or month: whatever the export's date column holds)."""

    model_config = ConfigDict(frozen=True)

    id: str
    date: date
    campaign_id: str
    campaign: str
    channel: str
    spend_minor: int = Field(ge=0)
    attributed_sales_minor: int | None = Field(default=None, ge=0)
    product_id: str | None = None


def _key(name: str) -> str:
    return re.sub(r"[\s\-/.]+", "_", name.strip().lower()).strip("_")


def _lookup(columns: dict[str, tuple[str, ...]]) -> dict[str, str]:
    return {alias: field for field, aliases in columns.items() for alias in aliases}


def _map(header: list[str], columns: dict[str, tuple[str, ...]]) -> dict[str, int]:
    lookup = _lookup(columns)
    out: dict[str, int] = {}
    for i, name in enumerate(header):
        field = lookup.get(_key(name))
        if field is not None and field not in out:
            out[field] = i
    return out


def detect_kind(header: list[str]) -> CsvKind | None:
    """Which record a CSV holds, from its header alone. Ad spend and products first: their columns are distinctive;
    a statement has a description and an amount; sales lines name a product and a quantity."""
    keys = {_key(h) for h in header}

    def has(columns: dict[str, tuple[str, ...]], *fields: str) -> bool:
        return all(keys & set(columns[f]) for f in fields)

    if has(AD_COLUMNS, "campaign", "spend"):
        return "ad_spend"
    if has(PRODUCT_COLUMNS, "name", "price") and (has(PRODUCT_COLUMNS, "cost") or has(PRODUCT_COLUMNS, "stock")) \
            and not has(SALES_COLUMNS, "date"):
        return "products"
    if has(STATEMENT_COLUMNS, "date", "description") and (
            has(STATEMENT_COLUMNS, "amount") or has(STATEMENT_COLUMNS, "debit", "credit")):
        return "bank"
    if has(SALES_COLUMNS, "date", "product", "qty"):
        return "sales"
    return None


def read_csv(data: bytes | str) -> tuple[list[str], list[tuple[int, list[str]]]]:
    """(header, [(line, row)]) with blank rows skipped. Raises RecordsError for an empty or non-UTF-8 file."""
    if isinstance(data, bytes):
        try:
            data = data.decode("utf-8-sig")
        except UnicodeDecodeError:
            raise RecordsError([RowError(line=0, message="file is not UTF-8 text")]) from None
    reader = csv.reader(io.StringIO(data, newline=""))
    header = next(reader, None)
    if not header or not any(h.strip() for h in header):
        raise RecordsError([RowError(line=1, message="empty file")])
    rows = [(n, r) for n, r in enumerate(reader, start=2) if any(c.strip() for c in r)]
    if not rows:
        raise RecordsError([RowError(line=2, message="no rows under the header")])
    if len(rows) > MAX_ROWS:
        raise RecordsError([RowError(line=MAX_ROWS + 2, message=f"more than {MAX_ROWS} rows")])
    return header, rows


def _date(raw: str) -> date:
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(raw.strip(), fmt).date()
        except ValueError:
            continue
    if re.fullmatch(r"\d{4}-\d{2}", raw.strip()):  # a monthly export: the first of the month
        return date.fromisoformat(raw.strip() + "-01")
    raise ValueError(f"bad date {raw!r} (expected YYYY-MM-DD)")


def _name(raw: str, what: str) -> str:
    s = " ".join(raw.split())
    if not s:
        raise ValueError(f"missing {what}")
    if not NAME.match(s):
        raise ValueError(f"{what} {s[:30]!r} has characters that are not allowed or is longer than 60")
    return s


def slug_id(text: str) -> str:
    return SLUG.sub("-", text.strip().upper().replace(" ", "-")).strip("-")[:40] if False else \
        re.sub(r"[^A-Z0-9]+", "-", text.strip().upper()).strip("-")[:40]


def _count(raw: str, what: str, *, allow_negative: bool = False) -> int:
    try:
        n = int(raw.strip().replace(",", ""))
    except ValueError:
        raise ValueError(f"bad {what} {raw!r} (expected a whole number)") from None
    if n < 0 and not allow_negative:
        raise ValueError(f"{what} must not be negative")
    return n


def _required(cols: dict[str, int], needed: list[str], label: str) -> None:
    missing = [f for f in needed if f not in cols]
    if missing:
        raise RecordsError([RowError(line=1, message=f"{label}: missing column(s): {', '.join(missing)}")])


def _cell(row: list[str], cols: dict[str, int], field: str) -> str:
    i = cols.get(field)
    return row[i].strip() if i is not None and i < len(row) else ""


def parse_products(data: bytes | str, currency: str) -> tuple[Product, ...]:
    header, rows = read_csv(data)
    cols = _map(header, PRODUCT_COLUMNS)
    _required(cols, ["name", "price"], "products")
    errors: list[RowError] = []
    out: dict[str, Product] = {}
    for line, row in rows:
        try:
            name = _name(_cell(row, cols, "name"), "product name")
            pid = slug_id(_cell(row, cols, "id") or name)
            if not pid:
                raise ValueError("product needs a SKU or a name with letters or digits")
            if pid in out:
                raise ValueError(f"product {pid} appears twice")
            price = parse_minor(_cell(row, cols, "price"), currency)
            raw_cost = _cell(row, cols, "cost")
            cost = parse_minor(raw_cost, currency) if raw_cost else None
            if price <= 0 or (cost is not None and cost < 0):
                raise ValueError("price must be above zero and cost not negative")
            raw_stock = _cell(row, cols, "stock")
            category = _cell(row, cols, "category")
            supplier = _cell(row, cols, "supplier")
            out[pid] = Product(id=pid, name=name, category=_name(category, "category") if category else None,
                               supplier_id=_name(supplier, "supplier") if supplier else None, price_minor=price,
                               cost_minor=cost, stock=_count(raw_stock, "stock") if raw_stock else None)
        except (AmountError, ValueError) as e:
            errors.append(RowError(line=line, message=str(e)))
    if errors:
        raise RecordsError(errors)
    return tuple(sorted(out.values(), key=lambda p: p.id))


def _product_index(products: tuple[Product, ...]) -> dict[str, Product]:
    index: dict[str, Product] = {}
    for p in products:
        index[p.id.lower()] = p
        index[p.name.lower()] = p
    return index


def parse_sales(data: bytes | str, currency: str, products: tuple[Product, ...]) -> tuple[SaleLine, ...]:
    """Per-product sale lines. Cost comes from the product's cost price (products must be uploaded first); a
    negative qty is a return."""
    header, rows = read_csv(data)
    cols = _map(header, SALES_COLUMNS)
    _required(cols, ["date", "product", "qty"], "sales")
    if "revenue" not in cols and "unit_price" not in cols:
        raise RecordsError([RowError(line=1, message="sales: missing column revenue (or unit_price)")])
    if not products:
        raise RecordsError([RowError(line=0, message="add your products file first: sales are matched to it")])
    index = _product_index(products)
    errors: list[RowError] = []
    parsed: list[dict] = []
    for line, row in rows:
        try:
            day = _date(_cell(row, cols, "date"))
            raw_product = _cell(row, cols, "product")
            product = index.get(raw_product.lower()) or index.get(slug_id(raw_product).lower())
            if product is None:
                raise ValueError(f"product {raw_product[:30]!r} is not in your products file")
            qty = _count(_cell(row, cols, "qty"), "qty", allow_negative=True)
            if qty == 0:
                raise ValueError("qty is zero")
            if "revenue" in cols and _cell(row, cols, "revenue"):
                revenue = parse_minor(_cell(row, cols, "revenue"), currency)
            else:
                revenue = parse_minor(_cell(row, cols, "unit_price"), currency) * qty
            if product.cost_minor is None:
                raise ValueError(f"product {product.id} has no cost price in your products file")
            parsed.append({"date": day, "product_id": product.id, "qty": qty, "revenue_minor": revenue,
                           "cost_minor": product.cost_minor * qty})
        except (AmountError, ValueError) as e:
            errors.append(RowError(line=line, message=str(e)))
    if errors:
        raise RecordsError(errors)
    seen: Counter[tuple] = Counter()
    out = []
    for r in parsed:
        key = (r["date"].isoformat(), r["product_id"], r["qty"], r["revenue_minor"])
        seen[key] += 1
        sid = "SL-" + hashlib.sha256(repr((key, seen[key])).encode()).hexdigest()[:16]
        out.append(SaleLine(id=sid, **r))
    return tuple(sorted(out, key=lambda s: (s.date, s.id)))


def parse_ad_spend(data: bytes | str, currency: str) -> tuple[AdSpendLine, ...]:
    header, rows = read_csv(data)
    cols = _map(header, AD_COLUMNS)
    _required(cols, ["date", "campaign", "spend"], "ad spend")
    errors: list[RowError] = []
    parsed: list[dict] = []
    for line, row in rows:
        try:
            campaign = _name(_cell(row, cols, "campaign"), "campaign")
            channel = _name(_cell(row, cols, "channel") or "Other", "channel")
            raw_sales = _cell(row, cols, "attributed_sales")
            raw_product = _cell(row, cols, "product")
            spend = parse_minor(_cell(row, cols, "spend"), currency)
            sales = parse_minor(raw_sales, currency) if raw_sales else None
            if spend < 0 or (sales is not None and sales < 0):
                raise ValueError("spend and sales must not be negative")
            parsed.append({"date": _date(_cell(row, cols, "date")), "campaign": campaign,
                           "campaign_id": slug_id(campaign).lower(), "channel": channel, "spend_minor": spend,
                           "attributed_sales_minor": sales,
                           "product_id": slug_id(raw_product) if raw_product else None})
        except (AmountError, ValueError) as e:
            errors.append(RowError(line=line, message=str(e)))
    if errors:
        raise RecordsError(errors)
    seen: Counter[tuple] = Counter()
    out = []
    for r in parsed:
        key = (r["date"].isoformat(), r["campaign_id"], r["channel"], r["spend_minor"], r["attributed_sales_minor"])
        seen[key] += 1
        out.append(AdSpendLine(id="AD-" + hashlib.sha256(repr((key, seen[key])).encode()).hexdigest()[:16], **r))
    return tuple(sorted(out, key=lambda a: (a.date, a.id)))


# ---- Storage: canonical CSVs in the business's records folder (same files a seeded business has) -------------

PRODUCT_FIELDS = ["id", "name", "category", "supplier_id", "price_minor", "cost_minor", "stock"]
SALE_FIELDS = ["id", "date", "product_id", "qty", "revenue_minor", "cost_minor"]
AD_FIELDS = ["id", "date", "campaign_id", "campaign", "channel", "spend_minor", "attributed_sales_minor", "product_id"]


def _write(path: Path, fields: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".csv.tmp")
    with tmp.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: ("" if v is None else v) for k, v in r.items()})
    tmp.replace(path)


def _read(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    with path.open(encoding="utf-8", newline="") as f:
        return [{k: (v if v != "" else None) for k, v in r.items()} for r in csv.DictReader(f)]


def load_ad_spend_csv(path: Path) -> tuple[AdSpendLine, ...]:
    return tuple(sorted((AdSpendLine.model_validate(r) for r in _read(path)), key=lambda a: (a.date, a.id)))


def save_products(folder: Path, products: tuple[Product, ...]) -> tuple[int, int]:
    """Merge by product ID (a re-upload updates prices, cost and stock). Returns (added, updated)."""
    path = folder / "products.csv"
    current = {r["id"]: r for r in _read(path)}
    added = sum(p.id not in current for p in products)
    for p in products:
        current[p.id] = p.model_dump(mode="json")
    _write(path, PRODUCT_FIELDS, [current[k] for k in sorted(current)])
    return added, len(products) - added


def _merge(path: Path, fields: list[str], rows: list[BaseModel], sort_key) -> tuple[int, int]:
    current = {r["id"]: r for r in _read(path)}
    added = 0
    for r in rows:
        if r.id not in current:  # type: ignore[attr-defined]
            current[r.id] = r.model_dump(mode="json")  # type: ignore[attr-defined]
            added += 1
    _write(path, fields, sorted(current.values(), key=sort_key))
    return added, len(rows) - added


def save_sales(folder: Path, lines: tuple[SaleLine, ...]) -> tuple[int, int]:
    """Append new sale lines (IDs are content hashes, so a re-upload adds nothing). Returns (added, duplicates)."""
    return _merge(folder / "sale_lines.csv", SALE_FIELDS, list(lines), lambda r: (r["date"], r["id"]))


def save_ad_spend(folder: Path, lines: tuple[AdSpendLine, ...]) -> tuple[int, int]:
    return _merge(folder / "ad_spend.csv", AD_FIELDS, list(lines), lambda r: (r["date"], r["id"]))
