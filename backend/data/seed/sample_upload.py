"""Sample files for the onboarding demo: a new fashion shop's first upload (synthetic, deterministic).

    python backend/data/seed/sample_upload.py      -> backend/data/samples/fashion_shop/

Writes what a real owner would drag in: three months of bank statement and per-product sales, a products file with
cost, price and stock, an ad spend export where one campaign loses money, three supplier invoice PDFs and a receipt
photo. The files are committed so the demo upload always works; re-running this script reproduces them byte for byte.

Planted, so the first brief has something to say: a campaign whose attributed sales are below its spend, a product
returned far more often than the rest, a product about to sell out and one that is not selling.
"""

import csv
import random
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from data.seed.mailbox import invoice_pdf, receipt_png  # noqa: E402

OUT = Path(__file__).resolve().parents[1] / "samples" / "fashion_shop"
TODAY = date(2026, 10, 19)
START = TODAY - timedelta(days=91)
SHOP = "Rosa & Thread"

# sku, name, category, cost, price, stock, mean units a day
PRODUCTS = [
    ("KURTA-COT", "Cotton kurta", "tops", 1100, 2900, 34, 1.6),
    ("LINEN-SHIRT", "Linen shirt", "tops", 1400, 3400, 4, 1.2),       # about to sell out
    ("DENIM-JKT", "Denim jacket", "outerwear", 2600, 5900, 22, 0.6),  # comes back too often
    ("MAXI-DRESS", "Floral maxi dress", "dresses", 1900, 4900, 18, 0.8),
    ("SLIM-CHINO", "Slim chinos", "bottoms", 1300, 3200, 26, 0.9),
    ("SILK-SCARF", "Silk scarf", "accessories", 900, 2400, 60, 0.07),  # not selling
    ("TOTE-BAG", "Canvas tote bag", "accessories", 500, 1500, 40, 0.7),
    ("LEATHER-BELT", "Leather belt", "accessories", 800, 2200, 30, 0.5),
]
RETURN_RATE = {"DENIM-JKT": 0.24}
CAMPAIGNS = [  # name, platform, weekly spend (minor), return on ad spend
    ("Festive Kurta Push", "Instagram", 6000, 3.4),
    ("Summer Linen Sale", "Facebook", 8000, 0.55),   # costs more than it brings in
    ("Brand Search", "Google", 3500, 2.1),
]


def money(minor: int) -> str:
    return f"{minor / 100:.2f}"


def days():
    d = START
    while d < TODAY:
        yield d
        d += timedelta(days=1)


def write_csv(path: Path, header: list[str], rows: list[list]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(header)
        w.writerows(rows)


def build() -> None:
    rng = random.Random(20261019)
    OUT.mkdir(parents=True, exist_ok=True)

    write_csv(OUT / "products.csv", ["sku", "name", "category", "cost_price", "sale_price", "stock"],
              [[s, n, c, money(cost), money(price), stock] for s, n, c, cost, price, stock, _ in PRODUCTS])

    sales, daily_revenue = [], {}
    for d in days():
        weekend = d.weekday() >= 4
        total = 0
        for sku, _, _, _, price, _, rate in PRODUCTS:
            mean = rate * (1.5 if weekend else 1.0)
            qty = sum(rng.random() < mean / 3 for _ in range(3))
            if qty:
                sales.append([d.isoformat(), sku, qty, money(qty * price)])
                total += qty * price
            if sku in RETURN_RATE and qty and rng.random() < RETURN_RATE[sku] * 1.6:
                sales.append([d.isoformat(), sku, -1, money(-price)])
                total -= price
        daily_revenue[d] = total
    write_csv(OUT / "sales.csv", ["date", "sku", "qty", "amount"], sales)

    ads = []
    for week in range(13):
        d = START + timedelta(days=7 * week)
        for name, platform, spend, roas in CAMPAIGNS:
            s = round(spend * rng.uniform(0.85, 1.15))
            ads.append([d.isoformat(), name, platform, money(s), money(round(s * roas * rng.uniform(0.9, 1.1)))])
    write_csv(OUT / "ad_spend.csv", ["date", "campaign", "platform", "spend", "attributed_sales"], ads)

    bank, balance = [], 650000
    ref = 0

    def row(d: date, desc: str, cp: str, amount: int) -> None:
        nonlocal balance, ref
        balance += amount
        ref += 1
        bank.append([d.isoformat(), desc, cp, money(amount), money(balance), f"RT-{ref:05d}"])

    for d in days():
        rev = daily_revenue[d]
        if rev > 0:
            card = round(rev * 0.55)
            row(d, "Card settlement", "Acquirer card sales", card)
            row(d, "Merchant fee card sales", "Acquirer card sales", -round(card * 0.024))
            row(d, "QR payment received", "Wallet customer", rev - card)
        if d.weekday() == 0:
            row(d, "Meta ads boost", "Meta Platforms", -round(14000 * rng.uniform(0.9, 1.1)))
            row(d, "Google ads", "Google Ads", -round(3500 * rng.uniform(0.9, 1.1)))
        if d.day == 1:
            row(d, "Shop rent", "Banyan Properties", -120000)
            row(d, "Payroll staff wages", "Payroll", -180000)
        if d.day == 5:
            row(d, "Electricity bill", "City Power Co", -round(9000 * rng.uniform(0.9, 1.2)))
            row(d, "Broadband internet", "FiberNet Broadband", -4500)
        if d.day in (8, 22):
            row(d, "Garments collection order", "Indigo Loom Textiles", -round(150000 * rng.uniform(0.8, 1.2)))
        if d.day == 15:
            row(d, "Accessories order", "Kora Accessories", -round(40000 * rng.uniform(0.8, 1.2)))
            row(d, "Paper bags and packaging", "Wrap & Co Packaging", -6500)
        if d.weekday() == 5 and rng.random() < 0.5:
            row(d, "Refund to customer", "Customer refund", -round(5900 * rng.uniform(0.5, 1.0)))
    write_csv(OUT / "bank.csv", ["date", "description", "counterparty", "amount", "balance", "reference"], bank)

    shop_lines = [SHOP, "12 Market Lane", "accounts@rosathread.example"]
    (OUT / "invoice_indigo_loom.pdf").write_bytes(invoice_pdf(
        seller="Indigo Loom Textiles", seller_lines=["44 Weaver Street", "billing@indigoloom.example"],
        number="ILT-2026-1187", issued=TODAY - timedelta(days=4), due=TODAY + timedelta(days=26), bill_to=shop_lines,
        lines=[("Cotton kurta, assorted sizes", 40, 1100), ("Linen shirt, white and sand", 30, 1400)],
        terms="Payment terms: 30 days.", remit=["Pay to: Indigo Loom Textiles"]))
    (OUT / "invoice_kora_accessories.pdf").write_bytes(invoice_pdf(
        seller="Kora Accessories", seller_lines=["8 Craft Row", "accounts@koraaccessories.example"],
        number="KA-5521", issued=TODAY - timedelta(days=2), due=TODAY + timedelta(days=13), bill_to=shop_lines,
        lines=[("Leather belt, brown", 20, 800), ("Canvas tote bag", 30, 500)],
        terms="Payment terms: 15 days.", remit=["Pay to: Kora Accessories"]))
    (OUT / "invoice_wrap_and_co.pdf").write_bytes(invoice_pdf(
        seller="Wrap & Co Packaging", seller_lines=["2 Mill Road", "hello@wrapandco.example"],
        number="WC-0932", issued=TODAY - timedelta(days=6), due=TODAY + timedelta(days=8), bill_to=shop_lines,
        lines=[("Paper carrier bags, large", 500, 9), ("Gift boxes", 120, 35)],
        terms="Payment terms: 14 days.", remit=["Pay to: Wrap & Co Packaging"]))
    items = [("STEAMER CLOTH", 450), ("HANGERS X20", 1200), ("PRICE TAGS", 350)]
    total = sum(a for _, a in items)
    (OUT / "receipt_hardware.png").write_bytes(receipt_png(
        "MARKET HARDWARE", "3 STATION RD", TODAY - timedelta(days=3), items, total, total, 2000))


if __name__ == "__main__":
    build()
    print(f"wrote {sorted(p.name for p in OUT.iterdir())} to {OUT}")
