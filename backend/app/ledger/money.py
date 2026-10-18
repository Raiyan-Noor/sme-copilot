"""Money as integer minor units (CLAUDE.md, Conventions).

Parsing turns statement text into an exact int with Decimal, never float, and refuses amounts with more decimal
places than the currency has (no silent rounding). Formatting happens only at render time (Fact.display).
Currency is config, not code: the product is region-neutral.
"""

import re
from decimal import Decimal, InvalidOperation

_GROUPED = re.compile(r"\d{1,3}(?:,\d{3})+")

# ISO 4217 minor-unit exponents for the currencies we accept.
CURRENCY_EXPONENT: dict[str, int] = {
    "USD": 2, "EUR": 2, "GBP": 2, "CNY": 2, "HKD": 2, "SGD": 2, "AUD": 2, "CAD": 2, "INR": 2, "BDT": 2,
    "PKR": 2, "LKR": 2, "IDR": 2, "MYR": 2, "PHP": 2, "THB": 2, "NGN": 2, "KES": 2, "GHS": 2, "ZAR": 2,
    "EGP": 2, "BRL": 2, "MXN": 2, "AED": 2, "SAR": 2, "TRY": 2, "CHF": 2,
    "JPY": 0, "KRW": 0, "VND": 0, "UGX": 0, "XOF": 0,
    "KWD": 3, "BHD": 3, "OMR": 3, "JOD": 3, "TND": 3,
}

# Unambiguous symbols only; every other currency renders with its ISO code.
CURRENCY_SYMBOL: dict[str, str] = {"USD": "$", "EUR": "€", "GBP": "£", "JPY": "¥", "INR": "₹", "BDT": "৳"}


class AmountError(ValueError):
    """An amount string could not be parsed exactly into minor units."""


def exponent(currency: str) -> int:
    try:
        return CURRENCY_EXPONENT[currency]
    except KeyError:
        raise AmountError(f"unsupported currency {currency!r}") from None


def parse_minor(text: str, currency: str, decimal_sep: str = ".") -> int:
    """Parse '1,234.56', '-12.5', '(12.50)' or '+3' into signed minor units.

    The thousands separator is whichever of ',' / '.' is not the decimal separator; spaces are ignored.
    Raises AmountError on anything that is not an exact amount in this currency.
    """
    if decimal_sep not in {".", ","}:
        raise AmountError(f"decimal separator must be '.' or ',', not {decimal_sep!r}")
    exp = exponent(currency)
    s = text.strip().replace(" ", "").replace(" ", "")
    negative = False
    if s.startswith("(") and s.endswith(")"):
        negative, s = True, s[1:-1]
    if s[:1] in {"-", "+"}:
        negative, s = negative ^ (s[0] == "-"), s[1:]
    thousands = "," if decimal_sep == "." else "."
    whole, _, frac = s.partition(decimal_sep)
    # Grouping must be exact, so '12,50' under the wrong decimal separator fails instead of becoming 1250.
    if thousands in whole and not _GROUPED.fullmatch(whole.replace(thousands, ",")):
        raise AmountError(f"bad thousands grouping in {text!r}")
    s = whole.replace(thousands, "") + ("." + frac if frac or s.endswith(decimal_sep) else "")
    if not s or not all(c.isascii() and (c.isdigit() or c == ".") for c in s):
        raise AmountError(f"not an amount: {text!r}")
    try:
        value = Decimal(s)
    except InvalidOperation:
        raise AmountError(f"not an amount: {text!r}") from None
    scaled = value.scaleb(exp)
    if scaled != scaled.to_integral_value():
        raise AmountError(f"{text!r} has more than {exp} decimal places for {currency}")
    minor = int(scaled)
    return -minor if negative else minor


def format_minor(minor: int, currency: str) -> str:
    """Render minor units for display, e.g. -123456 USD -> '-$1,234.56'. Render time only."""
    exp = exponent(currency)
    sign = "-" if minor < 0 else ""
    whole, frac = divmod(abs(minor), 10**exp) if exp else (abs(minor), 0)
    number = f"{whole:,}" + (f".{frac:0{exp}d}" if exp else "")
    symbol = CURRENCY_SYMBOL.get(currency)
    return f"{sign}{symbol}{number}" if symbol else f"{sign}{currency} {number}"
