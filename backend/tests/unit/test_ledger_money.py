"""Money parsing and formatting: exact integer minor units, never rounded."""

import pytest

from app.ledger.money import AmountError, format_minor, parse_minor


@pytest.mark.parametrize(
    "text, currency, sep, expected",
    [
        ("12.34", "USD", ".", 1234),
        ("-12.34", "USD", ".", -1234),
        ("+5", "USD", ".", 500),
        ("(12.50)", "USD", ".", -1250),
        ("1,234,567.89", "USD", ".", 123456789),
        ("1.234,56", "EUR", ",", 123456),
        ("0.1", "USD", ".", 10),
        ("1500", "JPY", ".", 1500),
        ("1.250", "KWD", ".", 1250),
        (" 7.00 ", "USD", ".", 700),
    ],
)
def test_parse_minor(text, currency, sep, expected):
    value = parse_minor(text, currency, sep)
    assert value == expected
    assert type(value) is int


@pytest.mark.parametrize(
    "text, currency, sep",
    [
        ("1.234", "USD", "."),  # more decimals than the currency has: never rounded
        ("1.5", "JPY", "."),
        ("12,50", "USD", "."),  # wrong decimal separator must fail, not become 1250
        ("1,23,456.00", "USD", "."),
        ("12.50", "EUR", ","),
        ("abc", "USD", "."),
        ("", "USD", "."),
        ("$12", "USD", "."),
        ("1e3", "USD", "."),
        ("١٢", "USD", "."),  # non-ASCII digits
        ("12", "XXX", "."),  # unsupported currency
    ],
)
def test_parse_minor_rejects(text, currency, sep):
    with pytest.raises(AmountError):
        parse_minor(text, currency, sep)


@pytest.mark.parametrize(
    "minor, currency, expected",
    [
        (123456, "USD", "$1,234.56"),
        (-5, "USD", "-$0.05"),
        (0, "USD", "$0.00"),
        (1500, "JPY", "¥1,500"),
        (1250, "KWD", "KWD 1.250"),
        (100000, "BDT", "৳1,000.00"),
    ],
)
def test_format_minor(minor, currency, expected):
    assert format_minor(minor, currency) == expected
