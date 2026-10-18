"""CSV statement ingestion: exact minor units, all-or-nothing validation, PII tokenized, idempotent re-import."""

import re
import sqlite3

import pytest

from app.ledger import (
    StatementError,
    TenantError,
    create_tenant,
    ingest_statement,
    load_snapshot,
    open_tenant,
    tenant_path,
)
from app.ledger.pii import TOKEN, reveal

ACCOUNT = "0012345678901"

STATEMENT = """date,description,amount,balance,counterparty,counterparty_phone,reference,channel,category
2026-09-01,Opening float,500.00,500.00,,,,cash,
2026-09-01,Wallet sale from 01712345678,12.50,512.50,Walk-in,01712345678,TRX1001,mobile_wallet,sales
2026-09-02,Rent September,-300.00,212.50,Landlord Ltd,,RENT-SEP,bank_transfer,Rent
2026-09-02,Coffee,-2.00,210.50,Corner Cafe,,,card,
2026-09-03,Coffee,-2.00,208.50,Corner Cafe,,,card,
"""


@pytest.fixture
def conn(tmp_path):
    c = create_tenant(tmp_path / "shop.sqlite", "test-shop", "USD", pii_key=bytes(range(32)))
    yield c
    c.close()


def ingest(conn, text=STATEMENT, **kw):
    return ingest_statement(conn, text, source_name="sept.csv", account_number=ACCOUNT, **kw)


def _all_text(conn) -> str:
    """Every stored string except the vault and the PII key: where raw PII must never appear."""
    parts = []
    for table in ("accounts", "imports", "transactions"):
        for row in conn.execute(f"SELECT * FROM {table}"):  # noqa: S608 - fixed table names
            parts.extend(str(v) for v in row if isinstance(v, str))
    return "\n".join(parts)


def test_ingest_stores_exact_minor_units(conn):
    report = ingest(conn)
    assert (report.rows, report.inserted, report.duplicates) == (5, 5, 0)
    assert str(report.date_from) == "2026-09-01" and str(report.date_to) == "2026-09-03"
    snap = load_snapshot(conn)
    assert [t.amount_minor for t in snap.transactions] == [50000, 1250, -30000, -200, -200]
    assert [t.balance_minor for t in snap.transactions] == [50000, 51250, 21250, 21050, 20850]
    assert all(type(t.amount_minor) is int for t in snap.transactions)
    assert snap.business_id == "test-shop" and snap.currency == "USD"
    assert snap.transactions[2].category == "rent"
    assert snap.transactions[1].channel == "mobile_wallet"


def test_sqlite_refuses_non_integer_money(conn):
    ingest(conn)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE transactions SET amount_minor = 12.5")


def test_pii_never_stored_outside_vault(conn):
    report = ingest(conn)
    text = _all_text(conn)
    for raw in ("01712345678", ACCOUNT):
        assert raw not in text
    assert TOKEN.fullmatch(report.account_id)
    assert reveal(conn, report.account_id) == ACCOUNT
    wallet = load_snapshot(conn).transactions[1]
    assert wallet.counterparty_ref and reveal(conn, wallet.counterparty_ref) == "01712345678"
    assert TOKEN.search(wallet.description)


def test_identical_rows_in_one_file_both_kept(conn):
    ingest(conn)
    coffees = [t for t in load_snapshot(conn).transactions if t.description == "Coffee"]
    assert len(coffees) == 2 and coffees[0].id != coffees[1].id


def test_reimport_is_idempotent(conn):
    first = ingest(conn)
    again = ingest(conn)
    assert again.import_id == first.import_id
    assert (again.inserted, again.duplicates) == (0, 5)
    assert len(load_snapshot(conn).transactions) == 5
    row = conn.execute("SELECT inserted, duplicates FROM imports").fetchone()
    assert (row["inserted"], row["duplicates"]) == (5, 0)


def test_overlapping_statement_only_adds_new_rows(conn):
    ingest(conn)
    lines = STATEMENT.splitlines()
    overlap = "\n".join([lines[0], *lines[4:], "2026-09-04,Electricity,-45.10,163.40,Power Co,,,bank_transfer,"])
    report = ingest(conn, overlap)
    assert (report.inserted, report.duplicates) == (1, 2)
    assert len(load_snapshot(conn).transactions) == 6


def test_row_ids_stable_across_tenants_with_same_key(tmp_path):
    ids = []
    for name in ("a", "b"):
        c = create_tenant(tmp_path / f"{name}.sqlite", f"shop-{name}", "USD", pii_key=bytes(range(32)))
        ingest(c)
        ids.append([t.id for t in load_snapshot(c).transactions])
        c.close()
    assert ids[0] == ids[1]
    assert all(re.fullmatch(r"txn_[0-9a-f]{20}", i) for i in ids[0])


def test_debit_credit_columns_and_aliases(conn):
    text = (
        "Transaction Date,Narrative,Money Out,Money In,Running Balance\n"
        "2026-09-01,Sales,,1,200.00,1,200.00\n"
    )
    with pytest.raises(StatementError):  # unquoted thousands separator splits the field
        ingest(conn, text)
    text = (
        "Transaction Date,Narrative,Money Out,Money In,Running Balance,Branch\n"
        '2026-09-01,Sales,,"1,200.00","1,200.00",North\n'
        "2026-09-02,Supplier,450.25,,749.75,North\n"
    )
    report = ingest(conn, text)
    assert report.ignored_columns == ["Branch"]
    assert [t.amount_minor for t in load_snapshot(conn).transactions] == [120000, -45025]


def test_custom_decimal_and_date_format(tmp_path):
    c = create_tenant(tmp_path / "eu.sqlite", "eu-shop", "EUR", pii_key=bytes(range(32)))
    try:
        text = 'date,description,amount\n18/10/2026,Sale,"1.234,56"\n'
        ingest_statement(c, text, source_name="x.csv", account_number="DE89370400440532013000",
                         decimal_sep=",", date_format="%d/%m/%Y")
        t = load_snapshot(c).transactions[0]
        assert (str(t.posted_on), t.amount_minor) == ("2026-10-18", 123456)
    finally:
        c.close()


@pytest.mark.parametrize(
    "row, fragment",
    [
        ("2026-09-01,Sale,1.234", "decimal places"),
        ("2026-13-01,Sale,1.00", "bad date"),
        ("01/09/2026,Sale,1.00", "bad date"),
        ("2026-09-01,,1.00", "missing description"),
        ("2026-09-01,Sale,", "missing amount"),
        ("2026-09-01,Sale,0.00", "zero amount"),
        ("2026-09-01,Sale,ten", "not an amount"),
        ("2026-09-01,Sale", "expected 3 fields"),
    ],
)
def test_bad_rows_rejected(conn, row, fragment):
    with pytest.raises(StatementError) as exc:
        ingest(conn, f"date,description,amount\n{row}\n")
    assert fragment in str(exc.value)
    assert exc.value.errors[0].line == 2


def test_one_bad_row_rejects_whole_file_and_leaves_no_trace(conn):
    text = "date,description,amount\n2026-09-01,From 01712345678,5.00\n2026-09-02,Bad,1.005\n"
    with pytest.raises(StatementError) as exc:
        ingest(conn, text)
    assert [e.line for e in exc.value.errors] == [3]
    for table in ("transactions", "imports", "accounts", "pii_vault"):
        assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0  # noqa: S608


def test_all_errors_reported(conn):
    text = "date,description,amount\nx,Sale,1\n2026-09-01,Sale,1.001\n2026-09-02,Ok,1\n"
    with pytest.raises(StatementError) as exc:
        ingest(conn, text)
    assert [e.line for e in exc.value.errors] == [2, 3]


def test_debit_and_credit_both_set_rejected(conn):
    with pytest.raises(StatementError, match="exactly one"):
        ingest(conn, "date,description,debit,credit\n2026-09-01,X,1.00,2.00\n")


def test_currency_mismatch_rejected(conn):
    with pytest.raises(StatementError, match="does not match"):
        ingest(conn, "date,description,amount,currency\n2026-09-01,X,1.00,EUR\n")


@pytest.mark.parametrize(
    "text, fragment",
    [
        ("", "empty file"),
        ("date,amount\n2026-09-01,1\n", "description"),
        ("date,description\n2026-09-01,X\n", "amount"),
        ("date,description,amount,details\n", "two columns"),
        ("date,description,amount\n", "no transactions"),
    ],
)
def test_bad_headers_rejected(conn, text, fragment):
    with pytest.raises(StatementError, match=fragment):
        ingest(conn, text)


def test_non_utf8_rejected(conn):
    with pytest.raises(StatementError, match="UTF-8"):
        ingest(conn, "date,description,amount\n2026-09-01,Caf\xe9,1.00\n".encode("latin-1"))


def test_utf8_bom_accepted(conn):
    report = ingest(conn, "﻿date,description,amount\n2026-09-01,Café,1.00\n".encode())
    assert report.inserted == 1


def test_tenant_paths_and_reopen(tmp_path):
    with pytest.raises(TenantError):
        tenant_path(tmp_path, "../etc")
    path = tenant_path(tmp_path, "maya-corner-store")
    assert path.parent == tmp_path
    create_tenant(path, "maya-corner-store", "USD").close()
    with pytest.raises(TenantError):
        create_tenant(path, "maya-corner-store", "USD")
    c = open_tenant(path)
    assert load_snapshot(c).business_id == "maya-corner-store"
    c.close()
    with pytest.raises(TenantError):
        open_tenant(tmp_path / "missing.sqlite")
    with pytest.raises(Exception):
        create_tenant(tmp_path / "x.sqlite", "x-shop", "XXX")


def test_scheduled_items_constraints(conn):
    insert = ("INSERT INTO scheduled_items (id, kind, category, due_date, amount_minor, source)"
              " VALUES (?, ?, ?, ?, ?, 'seed')")
    conn.execute(insert, ("sch_rent", "payable", "rent", "2026-11-01", 30000))
    assert conn.execute("SELECT status FROM scheduled_items").fetchone()["status"] == "open"
    for bad in [("sch_a", "payable", "rent", "2026-11-01", -5), ("sch_b", "payable", "rent", "2026-11-01", 1.5),
                ("sch_c", "transfer", "rent", "2026-11-01", 5), ("sch_d", "payable", "rent", "1 Nov", 5)]:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(insert, bad)


def test_scheduled_items_round_trip_to_model(conn):
    from app.ledger.scheduled import load_scheduled

    conn.execute(
        "INSERT INTO scheduled_items (id, kind, category, due_date, amount_minor, counterparty_id, reference, source)"
        " VALUES ('sch_b', 'receivable', 'customer_payment', '2026-11-05', 4500, 'cus_sunrise', 'INV-0042', 'seed'),"
        " ('sch_a', 'payable', 'rent', '2026-11-01', 30000, NULL, NULL, 'seed')"
    )
    items = load_scheduled(conn)
    assert [i.id for i in items] == ["sch_a", "sch_b"]
    assert (items[1].counterparty_id, items[1].reference, items[1].signed_minor) == ("cus_sunrise", "INV-0042", 4500)
    assert items[0].status == "open"


def test_cash_book_account_without_digits_gets_internal_id(conn):
    report = ingest_statement(conn, STATEMENT, source_name="cash.csv", account_number="CASH-MCS",
                              account_name="Cash book")
    assert report.account_id == "book_cash_mcs"
    assert not TOKEN.fullmatch(report.account_id)
    assert conn.execute("SELECT COUNT(*) FROM pii_vault WHERE value = 'CASHMCS'").fetchone()[0] == 0
    bank = ingest(conn)
    assert bank.account_id != report.account_id and TOKEN.fullmatch(bank.account_id)
    accounts = {r["id"] for r in conn.execute("SELECT id FROM accounts")}
    assert accounts == {"book_cash_mcs", bank.account_id}


@pytest.mark.parametrize("label", ["", "  ", "--"])
def test_empty_account_identifier_rejected(conn, label):
    with pytest.raises(StatementError, match="account identifier"):
        ingest_statement(conn, STATEMENT, source_name="x.csv", account_number=label)
