"""PII tokenization: phone numbers, national IDs and account numbers never survive into stored text."""

import re

import pytest

from app.ledger.pii import TOKEN, PiiKind, Tokenizer, reveal
from app.ledger.schema import create_tenant

KEY = bytes(range(32))


@pytest.fixture
def conn(tmp_path):
    c = create_tenant(tmp_path / "t.sqlite", "test-shop", "USD", pii_key=KEY)
    yield c
    c.close()


@pytest.fixture
def tok(conn):
    return Tokenizer(conn)


def test_token_shape_is_digit_free(tok):
    """Tokens can appear in planner output without tripping the Numeric Firewall digit check (invariant 4)."""
    t = tok.token(PiiKind.ACCOUNT, "1234567890")
    assert TOKEN.fullmatch(t)
    assert not re.search(r"\d", t)


def test_token_is_deterministic_and_normalized(tok):
    a = tok.token(PiiKind.PHONE, "017-1234 5678")
    assert a == tok.token(PiiKind.PHONE, "01712345678")
    assert a != tok.token(PiiKind.PHONE, "01712345679")
    assert tok.token(PiiKind.ACCOUNT, "gb29 nwbk") == tok.token(PiiKind.ACCOUNT, "GB29NWBK")


def test_token_depends_on_kind_and_tenant_key(tmp_path, tok):
    assert tok.token(PiiKind.PHONE, "01712345678") != tok.token(PiiKind.ACCOUNT, "01712345678")
    other = create_tenant(tmp_path / "o.sqlite", "other-shop", "USD", pii_key=bytes(32))
    try:
        assert Tokenizer(other).token(PiiKind.PHONE, "01712345678") != tok.token(PiiKind.PHONE, "01712345678")
    finally:
        other.close()


def test_reveal_round_trips(conn, tok):
    t = tok.token(PiiKind.NATIONAL_ID, "AB 123 456 789")
    assert reveal(conn, t) == "AB123456789"
    assert reveal(conn, "acct_aaaaaaaaaaaa") is None


def test_token_rejects_value_without_digits(tok):
    with pytest.raises(ValueError):
        tok.token(PiiKind.PHONE, "n/a")


@pytest.mark.parametrize(
    "text, secret, kind",
    [
        ("Wallet transfer from 01712345678", "01712345678", PiiKind.PHONE),
        ("Wallet transfer from 017-1234-5678", "017-1234-5678", PiiKind.PHONE),
        ("Call +44 20 7946 0958 re invoice", "+44 20 7946 0958", PiiKind.PHONE),
        ("Mobile: 0712 345 678", "0712 345 678", PiiKind.PHONE),
        ("Refund to A/C 0012345678901", "0012345678901", PiiKind.ACCOUNT),
        ("Refund to A/C-1234567890", "1234567890", PiiKind.ACCOUNT),
        ("Acct no. 987654", "987654", PiiKind.ACCOUNT),
        ("SEPA from GB29 NWBK 6016 1331 9268 19", "GB29 NWBK 6016 1331 9268 19", PiiKind.ACCOUNT),
        ("Card 4111 1111 1111 1111 purchase", "4111 1111 1111 1111", PiiKind.ACCOUNT),
        ("Transfer 123456789012 rent", "123456789012", PiiKind.ACCOUNT),
        ("KYC NID: 1990123456789 verified", "1990123456789", PiiKind.NATIONAL_ID),
        ("Passport No. A1234567", "A1234567", PiiKind.NATIONAL_ID),
        ("SSN 123-45-6789", "123-45-6789", PiiKind.NATIONAL_ID),
    ],
)
def test_scrub_replaces_pii(conn, tok, text, secret, kind):
    out = tok.scrub(text)
    digits = "".join(c for c in secret if c.isdigit())
    assert digits not in "".join(c for c in out if c.isdigit())
    tokens = TOKEN.findall(out)
    assert len(tokens) == 1
    assert tokens[0].startswith(f"{kind}_")
    assert reveal(conn, tokens[0]) is not None


@pytest.mark.parametrize(
    "text",
    [
        "POS sale 2026-10-18 till 3",
        "Rent October 2026",
        "Statement date 20261018",
        "INV-20261018-0042 paid",
        "Rice 25kg x 12 bags",
        "Total 1,234.56",
        "Order #4521",
        "Ref TRX99881234",
        "Card ****1234",
        "AB12 WEEK SALE PROMO",
    ],
)
def test_scrub_leaves_non_pii_alone(tok, text):
    assert tok.scrub(text) == text


def test_scrub_same_number_same_token(tok):
    a = tok.scrub("from 01712345678")
    b = tok.scrub("to 017 1234 5678")
    assert TOKEN.findall(a) == TOKEN.findall(b)


def test_tokens_survive_rescrub(tok):
    once = tok.scrub("from 01712345678")
    assert tok.scrub(once) == once
