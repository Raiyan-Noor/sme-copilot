"""CSV bank/wallet statement ingestion.

Canonical columns (headers are case-insensitive; common bank aliases are accepted, see COLUMN_ALIASES):

  date, description                    required
  amount                               signed, + money in, - money out
  debit, credit                        alternative to amount: unsigned, exactly one per row
  balance, counterparty, counterparty_account, counterparty_phone, reference, channel, category, currency

Rules
- Amounts become exact integer minor units (ledger/money.py); a bad amount is an error, never rounded.
- All-or-nothing: if any row fails validation, nothing is written and StatementError lists every bad line.
- PII is tokenized before anything is stored (ledger/pii.py). Unknown columns are dropped, never stored.
- Row IDs are a hash of the row's content (after tokenization) plus its occurrence number among identical rows in
  the file, so re-ingesting the same or an overlapping statement does not duplicate transactions.
- Statement text stays untrusted (invariant 2): it is stored for the owner's UI and for engine classification,
  never forwarded to the planner.
"""

import csv
import hashlib
import io
import re
import sqlite3
from collections import Counter
from collections.abc import Callable
from datetime import date, datetime

from pydantic import BaseModel

from app.ledger.money import AmountError, parse_minor
from app.ledger.pii import PiiKind, Tokenizer
from app.ledger.schema import get_meta

COLUMN_ALIASES: dict[str, tuple[str, ...]] = {
    "date": ("date", "posted_on", "posting_date", "transaction_date", "txn_date", "value_date", "booking_date"),
    "description": ("description", "details", "narrative", "memo", "particulars", "transaction_details"),
    "amount": ("amount", "signed_amount", "net_amount"),
    "debit": ("debit", "withdrawal", "withdrawals", "money_out", "paid_out", "dr"),
    "credit": ("credit", "deposit", "deposits", "money_in", "paid_in", "cr"),
    "balance": ("balance", "running_balance", "closing_balance"),
    "counterparty": ("counterparty", "payee", "payer", "merchant", "beneficiary"),
    "counterparty_account": ("counterparty_account", "payee_account", "beneficiary_account", "account_number"),
    "counterparty_phone": ("counterparty_phone", "payee_phone", "phone", "msisdn", "mobile"),
    "reference": ("reference", "ref", "transaction_id", "txn_id", "reference_number"),
    "channel": ("channel", "method", "payment_method", "type"),
    "category": ("category",),
    "currency": ("currency", "ccy"),
}
_ALIAS_TO_FIELD = {alias: field for field, aliases in COLUMN_ALIASES.items() for alias in aliases}
_SLUG = re.compile(r"[a-z][a-z0-9_]{0,47}")
MAX_TEXT = 200


class RowError(BaseModel):
    line: int  # 1-based line in the file, header is line 1
    message: str


class StatementError(ValueError):
    """The statement was rejected; nothing was written."""

    def __init__(self, errors: list[RowError]):
        self.errors = errors
        shown = "; ".join(f"line {e.line}: {e.message}" for e in errors[:5])
        more = f" (+{len(errors) - 5} more)" if len(errors) > 5 else ""
        super().__init__(f"statement rejected: {shown}{more}")


class IngestReport(BaseModel):
    import_id: str
    account_id: str
    rows: int
    inserted: int
    duplicates: int
    date_from: date
    date_to: date
    ignored_columns: list[str]


def _header_key(name: str) -> str:
    return re.sub(r"[\s\-/.]+", "_", name.strip().lower()).strip("_")


def _map_header(header: list[str]) -> tuple[dict[str, int], list[str]]:
    mapping: dict[str, int] = {}
    ignored: list[str] = []
    for i, name in enumerate(header):
        field = _ALIAS_TO_FIELD.get(_header_key(name))
        if field is None:
            ignored.append(name.strip())
        elif field in mapping:
            raise StatementError([RowError(line=1, message=f"two columns map to {field!r}")])
        else:
            mapping[field] = i
    missing = [f for f in ("date", "description") if f not in mapping]
    if "amount" not in mapping and not {"debit", "credit"} <= mapping.keys():
        missing.append("amount (or debit and credit)")
    if missing:
        raise StatementError([RowError(line=1, message=f"missing column(s): {', '.join(missing)}")])
    return mapping, ignored


def _account_id(tok: Tokenizer, account_number: str) -> str:
    """A PII token for a real account number; `book_<slug>` for an internal book such as a cash book ('CASH-MCS').

    Anything containing a digit is treated as PII and tokenized. A digit-free label cannot hold a phone, ID or
    account number, so it is kept readable; the `book_` prefix keeps it distinct from every token.
    """
    if any(c.isdigit() for c in account_number):
        return tok.token(PiiKind.ACCOUNT, account_number)
    slug = re.sub(r"[^a-z]+", "_", account_number.lower()).strip("_")[:40]
    if not slug:
        raise StatementError([RowError(line=0, message="account identifier is empty")])
    return f"book_{slug}"


def _text(value: str | None) -> str | None:
    s = " ".join((value or "").split())
    return s[:MAX_TEXT] if s else None


def _decode(data: bytes | str) -> str:
    if isinstance(data, str):
        return data
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise StatementError([RowError(line=0, message="file is not UTF-8")]) from None


def ingest_statement(
    conn: sqlite3.Connection,
    data: bytes | str,
    *,
    source_name: str,
    account_number: str,
    account_name: str = "Statement account",
    decimal_sep: str = ".",
    date_format: str = "%Y-%m-%d",
) -> IngestReport:
    """Validate and store one statement for one account. Atomic: all rows or none."""
    currency = get_meta(conn, "currency")
    if not currency:
        raise ValueError("not a tenant database")
    text = _decode(data)
    tok = Tokenizer(conn)
    file_sha = hashlib.sha256(text.encode()).hexdigest()

    reader = csv.reader(io.StringIO(text, newline=""))
    header = next(reader, None)
    if not header:
        raise StatementError([RowError(line=1, message="empty file")])
    cols, ignored = _map_header(header)

    def cell(row: list[str], field: str) -> str:
        i = cols.get(field)
        return row[i].strip() if i is not None and i < len(row) else ""

    errors: list[RowError] = []
    parsed: list[dict] = []
    try:
        account_id = _account_id(tok, account_number)
        for line, row in enumerate(reader, start=2):
            if not any(c.strip() for c in row):
                continue
            if len(row) != len(header):
                errors.append(RowError(line=line, message=f"expected {len(header)} fields, got {len(row)}"))
                continue
            try:
                parsed.append({"source_line": line, **_parse_row(row, cell, "amount" in cols, currency, decimal_sep, date_format, tok)})
            except (AmountError, ValueError) as e:
                errors.append(RowError(line=line, message=str(e)))
        if not parsed and not errors:
            errors.append(RowError(line=2, message="no transactions"))
        if errors:
            raise StatementError(errors)

        import_id = "imp_" + hashlib.sha256(f"{account_id}:{file_sha}".encode()).hexdigest()[:20]
        seen: Counter[tuple] = Counter()
        for r in parsed:
            key = (account_id, r["posted_on"], r["amount_minor"], r["description"], r["balance_minor"],
                   r["reference"], r["counterparty_ref"])
            seen[key] += 1
            r["id"] = "txn_" + hashlib.sha256(repr((key, seen[key])).encode()).hexdigest()[:20]

        with conn:
            conn.execute(
                "INSERT OR IGNORE INTO accounts (id, name, currency) VALUES (?, ?, ?)",
                (account_id, tok.scrub(_text(account_name) or "Statement account"), currency),
            )
            before = conn.total_changes
            conn.execute(
                "INSERT OR IGNORE INTO imports (id, account_id, source_name, file_sha256, row_count, inserted,"
                " duplicates) VALUES (?, ?, ?, ?, ?, 0, 0)",
                (import_id, account_id, tok.scrub(_text(source_name) or "statement.csv"), file_sha, len(parsed)),
            )
            new_import = conn.total_changes > before
            before = conn.total_changes
            conn.executemany(
                "INSERT OR IGNORE INTO transactions (id, account_id, posted_on, amount_minor, currency, description,"
                " counterparty, counterparty_ref, reference, channel, category, balance_minor, import_id,"
                " source_line) VALUES (:id, :account_id, :posted_on, :amount_minor, :currency, :description,"
                " :counterparty, :counterparty_ref, :reference, :channel, :category, :balance_minor, :import_id,"
                " :source_line)",
                [{**r, "account_id": account_id, "currency": currency, "import_id": import_id} for r in parsed],
            )
            inserted = conn.total_changes - before
            if new_import:
                conn.execute(
                    "UPDATE imports SET inserted = ?, duplicates = ? WHERE id = ?",
                    (inserted, len(parsed) - inserted, import_id),
                )
    except BaseException:
        conn.rollback()  # also drops pii_vault rows written while validating a rejected file
        raise

    dates = [r["posted_on"] for r in parsed]
    return IngestReport(
        import_id=import_id,
        account_id=account_id,
        rows=len(parsed),
        inserted=inserted,
        duplicates=len(parsed) - inserted,
        date_from=min(dates),
        date_to=max(dates),
        ignored_columns=ignored,
    )


def _parse_row(
    row: list[str],
    cell: Callable[[list[str], str], str],
    signed_amount: bool,
    currency: str,
    decimal_sep: str,
    date_format: str,
    tok: Tokenizer,
) -> dict:
    """One validated, tokenized row (without id, account or import). Raises ValueError/AmountError."""
    raw_date = cell(row, "date")
    try:
        posted_on = datetime.strptime(raw_date, date_format).date()
    except ValueError:
        raise ValueError(f"bad date {raw_date!r} (expected {date_format})") from None

    row_ccy = cell(row, "currency").upper()
    if row_ccy and row_ccy != currency:
        raise ValueError(f"currency {row_ccy} does not match business currency {currency}")

    if signed_amount:
        raw = cell(row, "amount")
        if not raw:
            raise ValueError("missing amount")
        amount = parse_minor(raw, currency, decimal_sep)
    else:
        debit, credit = cell(row, "debit"), cell(row, "credit")
        d = parse_minor(debit, currency, decimal_sep) if debit else 0
        c = parse_minor(credit, currency, decimal_sep) if credit else 0
        if d < 0 or c < 0:
            raise ValueError("debit and credit must not be negative")
        if (d == 0) == (c == 0):
            raise ValueError("exactly one of debit or credit must be non-zero")
        amount = c - d
    if amount == 0:
        raise ValueError("zero amount")

    raw_bal = cell(row, "balance")
    balance = parse_minor(raw_bal, currency, decimal_sep) if raw_bal else None

    description = _text(cell(row, "description"))
    if not description:
        raise ValueError("missing description")

    cp_ref = None
    if acct := cell(row, "counterparty_account"):
        cp_ref = tok.token(PiiKind.ACCOUNT, acct)
    elif phone := cell(row, "counterparty_phone"):
        cp_ref = tok.token(PiiKind.PHONE, phone)

    category = None
    if raw_cat := cell(row, "category"):
        category = re.sub(r"[^a-z0-9]+", "_", raw_cat.lower()).strip("_")
        if not _SLUG.fullmatch(category):
            raise ValueError(f"bad category {raw_cat!r}")

    def scrubbed(field: str) -> str | None:
        value = _text(cell(row, field))
        return tok.scrub(value) if value else None

    channel = scrubbed("channel")
    return {
        "posted_on": posted_on.isoformat(),
        "amount_minor": amount,
        "description": tok.scrub(description),
        "counterparty": scrubbed("counterparty"),
        "counterparty_ref": cp_ref,
        "reference": scrubbed("reference"),
        "channel": channel.lower()[:32] if channel else None,
        "category": category,
        "balance_minor": balance,
    }
