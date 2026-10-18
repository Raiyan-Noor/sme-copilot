"""One small synthetic ledger, used to show that swapping the Skill Pack changes outputs on the same rows.

Built in code (not from seed files) so pack tests do not depend on the seed generator; row text mirrors the seed's
statement formats. Planted, as of TODAY:
- daily wallet, card and cash sales, plus the internal-transfer legs that move wallet and cash money to the bank
  (these must never count as revenue);
- a monthly credit-customer invoice payment;
- a rice distributor and a fabric supplier with weekly purchases;
- two point-of-sale subscriptions (one redundant): monthly charges of 4,500 and 3,000 minor units;
- payment fees at 1.8% of digital sales (above grocery's 1.5% healthy max, under fashion's 2%);
- customer refunds at ~10% of sales (fashion counts them as refunds; grocery has no such category);
- one late fee, monthly rent and a monthly insurance premium.
"""

from datetime import date, timedelta

from app.clock import FixedClock
from app.ledger.snapshot import LedgerSnapshot, Transaction

TODAY = date(2026, 10, 19)
CLOCK = FixedClock(TODAY)
CURRENCY = "USD"
DAYS = 180

POS_CHEAP_MONTHLY = 3_000
DAILY_SALES = 40_000 + 20_000 + 30_000

Row = tuple[date, int, str, str, str | None]  # date, amount, counterparty, description, channel


def _transaction(n: int, row: Row) -> Transaction:
    d, amt, cp, desc, channel = row
    return Transaction(id=f"t{n:05d}", account_id="acct_test", posted_on=d, amount_minor=amt, currency=CURRENCY,
                       description=desc, counterparty=cp or None, channel=channel, import_id="imp_test",
                       source_line=n)


def snapshot_of(rows: list[Row]) -> LedgerSnapshot:
    txns = tuple(_transaction(n, r) for n, r in enumerate(sorted(rows, key=lambda r: r[0])))
    return LedgerSnapshot(business_id="pack-test", currency=CURRENCY, transactions=txns)


def build_snapshot() -> LedgerSnapshot:
    rows: list[Row] = []
    start = TODAY - timedelta(days=DAYS - 1)
    for i in range(DAYS):
        d = start + timedelta(days=i)
        rows.append((d, 40_000, "Wallet customer", "PAYMENT RECEIVED", "wallet"))
        rows.append((d, 20_000, "Acquirer Bank", "CARD SETTLEMENT", "card"))
        rows.append((d, 30_000, "", "CASH SALES Z-REPORT", "cash_sale"))
        rows.append((d, -round(60_000 * 0.018), "PayNest Wallet", "MERCHANT FEE MDR 1.8%", "fee"))
        rows.append((d, -9_000, "Wallet customer", "REFUND MIDI DRESS", "refund"))
        # Internal-transfer legs: wallet -> bank and cash -> bank, both sides.
        rows.append((d, -40_000, "Harbor Federal Bank", "SETTLEMENT TO BANK ACCT", "internal_transfer"))
        rows.append((d, 40_000, "PayNest Wallet", "PAYNEST SETTLEMENT MERCHANT", "internal_transfer"))
        rows.append((d, -30_000, "Harbor Federal Bank", "CASH DEPOSIT TO BANK", "internal_transfer"))
        rows.append((d, 30_000, "Maya's Corner Store", "CASH DEPOSIT BRANCH", "internal_transfer"))
        if i % 7 == 0:
            week = i // 7
            rows.append((d, -round(100_000 * 1.015**week), "Rice Distributor Ltd", "ACH PAYMENT RICE", "transfer"))
            rows.append((d, -round(150_000 * 1.015**week), "Silk Fabric Co", "ACH PAYMENT GARMENTS", "transfer"))
        if d.day == 1:
            rows.append((d, -300_000, "Landlord Properties", "RENT SHOP UNIT", "direct_debit"))
            rows.append((d, 50_000, "Sunrise Cafe", "TRANSFER FROM SUNRISE CAFE REF AR-001", "transfer"))
        if d.day == 5:
            rows.append((d, -4_500, "QuickPOS POS System", "QUICKPOS SUBSCRIPTION", "direct_debit"))
            rows.append((d, -POS_CHEAP_MONTHLY, "TillPro Point of Sale", "TILLPRO SUBSCRIPTION", "direct_debit"))
        if d.day == 8:
            rows.append((d, -8_500, "Shieldwell Insurance", "SHIELDWELL INSURANCE PREMIUM", "direct_debit"))
    rows.append((TODAY - timedelta(days=20), -2_500, "City Power", "CITY POWER LATE PAYMENT FEE", "direct_debit"))
    return snapshot_of(rows)
