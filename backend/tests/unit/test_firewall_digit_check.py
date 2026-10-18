"""Digit check (invariant 4): no number-like character in LLM output outside a valid {fact:<id>} placeholder."""

import pytest

from app.firewall import ViolationKind, check_output, is_numeric_char


def kinds(text: str, known=None) -> list[ViolationKind]:
    return [v.kind for v in check_output(text, known).violations]


# --- clean text -------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "",
        "Cash looks healthy this week.",
        "Your runway is {fact:runway_days} days.",
        "Payroll of {fact:payroll_amount} is due on {fact:payroll_due_date}.",
        "Revenue for the period was {fact:pnl.2026-09.revenue}.",  # digits inside a placeholder ID are fine
        "Balance as of {fact:cash:2026-10-18} is fine.",
        "{fact:a}{fact:b}",
        "About a week of buffer, roughly double last month.",  # words, not digits
    ],
)
def test_clean_text_passes(text):
    assert check_output(text).ok


def test_fact_ids_reported_in_order():
    assert check_output("{fact:b} then {fact:a} then {fact:b}").fact_ids == ("b", "a", "b")


# --- ASCII digits -------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "You have 12 days of cash.",
        "Pay the 1st invoice first.",
        "It's the 2nd, 3rd and 4th suppliers.",
        "Due 2026-10-20.",
        "Due 20/10/2026.",
        "Due Oct 20.",
        "Q4 looks slow.",
        "Margin is 23.5%.",
        "Owe $1,500.00",
        "Send it at 9am.",
        "Plan for the 90-day forecast.",
        "Version v2 of the plan.",
        "0",
        "Covid-19 era",
        "Call +44 20 7946 0000",
        "&#49;&#50; days",  # HTML entities still contain ASCII digits
        "%31%32 days",
        "1⃣ first",  # keycap emoji: an ASCII digit plus a combining mark
    ],
)
def test_ascii_digits_rejected(text):
    assert ViolationKind.DIGIT in kinds(text)


def test_digit_adjacent_to_placeholder_rejected():
    assert kinds("{fact:cash_balance}0") == [ViolationKind.DIGIT]
    assert kinds("1{fact:cash_balance}") == [ViolationKind.DIGIT]


def test_one_violation_per_numeric_run_with_positions():
    text = "On 2026-10-20 pay {fact:x} by 9am"
    violations = check_output(text).violations
    assert [v.snippet for v in violations] == ["2026", "10", "20", "9"]
    for v in violations:
        assert text[v.start : v.end] == v.snippet


# --- Unicode digits -----------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "ch",
    [
        "٣",  # ARABIC-INDIC DIGIT THREE
        "۵",  # EXTENDED ARABIC-INDIC DIGIT FIVE
        "१",  # DEVANAGARI DIGIT ONE
        "২",  # BENGALI DIGIT TWO
        "๓",  # THAI DIGIT THREE
        "３",  # FULLWIDTH DIGIT THREE
        "\U0001d7cf",  # MATHEMATICAL BOLD DIGIT ONE
        "\U0001d7e1",  # MATHEMATICAL DOUBLE-STRUCK DIGIT NINE
        "²",  # SUPERSCRIPT TWO
        "₃",  # SUBSCRIPT THREE
        "½",  # VULGAR FRACTION ONE HALF
        "①",  # CIRCLED DIGIT ONE
        "⒈",  # DIGIT ONE FULL STOP
        "Ⅻ",  # ROMAN NUMERAL TWELVE
        "ⅰ",  # SMALL ROMAN NUMERAL ONE
        "三",  # CJK numeral three
        "㏩",  # IDEOGRAPHIC TELEGRAPH SYMBOL FOR DAY TEN (So, but NFKC -> "10" + day)
        "㋀",  # IDEOGRAPHIC TELEGRAPH SYMBOL FOR JANUARY (NFKC -> "1" + month)
    ],
)
def test_unicode_numeric_chars_rejected(ch):
    assert is_numeric_char(ch)
    assert kinds(f"You have {ch} days.") == [ViolationKind.DIGIT]


@pytest.mark.parametrize("ch", ["a", "Z", " ", ".", "%", "$", "é", "—", "€", "​", "O", "l", "I"])
def test_non_numeric_chars_pass(ch):
    assert not is_numeric_char(ch)


def test_mixed_script_number_rejected():
    assert kinds("Pay ١٥٠٠ now") == [ViolationKind.DIGIT]


# --- placeholders that are not placeholders ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "{fact:1500}",  # IDs must start with a letter, or a placeholder could smuggle a number
        "{fact:_12}",
        "{fact:Runway12}",  # uppercase is not in the ID alphabet
        "{fact:runway ١}",
        "｛fact:runway１｝",  # fullwidth braces and digit
    ],
)
def test_digits_in_invalid_placeholders_rejected(text):
    assert ViolationKind.DIGIT in kinds(text)


@pytest.mark.parametrize(
    "text",
    [
        "{fact: runway_days}",
        "{fact:runway_days",
        "{FACT:runway_days}",
        "{ fact:runway_days}",
        "{fact:Runway}",
        "{fact:}",
        "{fact:{fact:x}}",
        "｛fact:runway｝",  # fullwidth braces
    ],
)
def test_malformed_placeholders_rejected(text):
    assert ViolationKind.MALFORMED_PLACEHOLDER in kinds(text)


def test_other_braces_are_not_placeholders():
    assert check_output("Use {curly braces} freely.").ok


# --- known fact IDs ----------------------------------------------------------------------------------------------


def test_unknown_fact_rejected_when_known_ids_given():
    assert kinds("{fact:runway_days} and {fact:made_up}", {"runway_days"}) == [ViolationKind.UNKNOWN_FACT]


def test_unknown_fact_not_checked_without_known_ids():
    assert check_output("{fact:made_up}").ok
