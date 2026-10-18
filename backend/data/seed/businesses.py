"""The two synthetic businesses as data: products, suppliers, bills, staff, credit customers and planted quirks.

Every name, domain (.example, RFC 2606), phone (+999, unassigned) and account number is fictional. Money is
integer minor units (cents). Dates are fixed so the output never depends on when the generator runs.
"""

from dataclasses import dataclass, field
from datetime import date

# Six months of history, inclusive, and the simulated "today" (CLAUDE.md: clock.py is the only time source).
HISTORY_START = date(2026, 4, 19)
HISTORY_END = date(2026, 10, 18)
SIM_TODAY = date(2026, 10, 19)
SCHEDULE_HORIZON_DAYS = 90


@dataclass(frozen=True)
class Product:
    id: str
    name: str
    category: str
    unit: str
    supplier_id: str
    price_minor: int
    cost_minor: int  # supplier unit cost at HISTORY_START
    base_units: float  # expected units per day before weekday, month and holiday factors
    holiday_sensitivity: float = 1.0  # 1.0 = follows the business's holiday uplift; 2.0 = twice the extra demand
    cost_creep_monthly: float = 0.0  # compounding monthly supplier price increase
    month_factors: tuple[tuple[int, float], ...] = ()
    reorder: bool = True  # False: bought once (fixed_orders), never replenished


@dataclass(frozen=True)
class Supplier:
    id: str
    name: str
    domain: str
    billing_email: str
    contact_name: str
    bank_name: str
    account_number: str
    account_since: date
    terms_days: int
    pay_lag_days: tuple[int, int]  # inclusive range of days from invoice to payment
    order_weekdays: tuple[int, ...] = ()  # Mon=0; weekly ordering
    order_month_days: tuple[int, ...] = ()  # monthly ordering
    early_pay_discount_pct: float = 0.0  # e.g. 2% if paid within early_pay_days
    early_pay_days: int = 0
    invoice_prefix: str = "INV"
    pack_category: str = ""  # the Skill Pack cogs category ID for this supplier
    lead_days: int = 1  # an order covers demand from order date + lead_days until the next order's coverage
    fixed_orders: tuple[tuple[date, str, int], ...] = ()  # (date, product_id, qty) one-off buys


@dataclass(frozen=True)
class Bill:
    """Monthly recurring outflow from the bank account."""

    id: str
    payee: str
    counterparty_id: str
    category: str  # the Skill Pack category ID
    day: int
    amount_minor: int
    description: str
    account_number: str
    sd_minor: int = 0
    month_factors: tuple[tuple[int, float], ...] = ()
    start: date | None = None
    scheduled: bool = True  # appears in scheduled_items (contract) or as an estimate when sd_minor > 0
    late: tuple[tuple[int, int, int], ...] = ()  # (month, days_late, late_fee_minor)


@dataclass(frozen=True)
class Customer:
    """Credit-account customer invoiced on a monthly cadence (credit sales are not in POS sale lines)."""

    id: str
    name: str
    email: str
    allowlisted: bool  # allow-list for T2 send_invoice_reminder
    issue_day: int
    terms_days: int
    amount_mean_minor: int
    amount_sd_minor: int
    first_issue: date
    pay_delay_days: tuple[int, int]
    unpaid: tuple[tuple[date, int], ...] = ()  # (issue_date, amount_minor): planted overdue dues


@dataclass(frozen=True)
class BusinessSpec:
    id: str
    name: str
    pack: str
    ref_prefix: str
    owner_name: str
    owner_email: str
    finance_email: str
    domain: str
    bank_name: str
    bank_account_number: str
    wallet_provider: str
    wallet_account_number: str
    cash_book_number: str  # internal label, no digits: the ingester keeps it readable (book_cash_mcs)
    opening_bank_minor: int
    opening_cash_minor: int
    cash_float_minor: int
    wallet_share: float
    wallet_fee_rate: float
    wallet_monthly_fee_minor: int
    ticket_mean_minor: int
    payer_pool: int
    weekday_factors: tuple[float, ...]
    day_noise_sd: float
    holiday_uplift: dict[str, float]  # holiday-calendar id -> flat demand multiplier over its window
    staff_net_monthly_minor: tuple[int, ...]
    payroll_day: int
    owner_draw_minor: int
    owner_draw_day: int
    petty_cash: tuple[tuple[str, int, int], ...]  # (label, min_minor, max_minor)
    petty_cash_daily_prob: float
    refund_daily_prob: float
    products: tuple[Product, ...]
    suppliers: tuple[Supplier, ...]
    bills: tuple[Bill, ...]
    customers: tuple[Customer, ...]
    known_domains: tuple[str, ...] = field(default=())


GROCERY = BusinessSpec(
    id="maya_corner_store",
    name="Maya's Corner Store",
    pack="grocery_retail",
    ref_prefix="MCS",
    owner_name="Maya Collins",
    owner_email="maya@mayascornerstore.example",
    finance_email="accounts@mayascornerstore.example",
    domain="mayascornerstore.example",
    bank_name="Harbor Federal Bank",
    bank_account_number="4410 2290 4471",
    wallet_provider="PayNest Wallet",
    wallet_account_number="PN-7781-0042",
    cash_book_number="CASH-MCS",
    opening_bank_minor=520_000,
    opening_cash_minor=20_000,
    cash_float_minor=20_000,
    wallet_share=0.46,
    wallet_fee_rate=0.018,
    wallet_monthly_fee_minor=1_500,
    ticket_mean_minor=1_250,
    payer_pool=320,
    weekday_factors=(0.90, 0.88, 0.92, 0.97, 1.12, 1.25, 0.96),
    day_noise_sd=0.08,
    holiday_uplift={"major_festival": 1.9, "minor_holiday": 1.3, "year_end": 1.1},
    staff_net_monthly_minor=(205_000, 185_000),
    payroll_day=28,
    owner_draw_minor=480_000,
    owner_draw_day=30,
    petty_cash=(("CLEANING SUPPLIES", 800, 3_500), ("SHOP REPAIRS", 1_500, 6_000), ("DELIVERY TIP", 300, 1_000)),
    petty_cash_daily_prob=0.22,
    refund_daily_prob=0.0,
    products=(
        Product("RICE-5KG", "Long-grain rice 5 kg", "staples", "bag", "sup_ggw", 1_499, 1_040, 14, 1.5,
                cost_creep_monthly=0.034),
        Product("RICE-BAS-2KG", "Basmati rice 2 kg", "staples", "bag", "sup_ggw", 849, 590, 9, 1.5),
        Product("FLOUR-2KG", "Wheat flour 2 kg", "staples", "bag", "sup_ggw", 329, 230, 12, 1.8),
        Product("OIL-1L", "Sunflower oil 1 L", "staples", "bottle", "sup_ggw", 449, 310, 10, 1.4),
        Product("SUGAR-1KG", "White sugar 1 kg", "staples", "bag", "sup_ggw", 219, 155, 11, 1.8),
        Product("LENTIL-1KG", "Red lentils 1 kg", "staples", "bag", "sup_ggw", 349, 235, 7, 1.2),
        Product("PASTA-500G", "Pasta 500 g", "staples", "pack", "sup_ggw", 179, 105, 16, 1.0),
        Product("TEA-100", "Black tea 100 bags", "beverages", "box", "sup_ggw", 499, 320, 6, 1.3),
        Product("WATER-6PK", "Bottled water 6-pack", "beverages", "pack", "sup_ggw", 349, 355, 18, 1.0),
        Product("MILK-1L", "Fresh milk 1 L", "dairy", "bottle", "sup_fresh", 139, 98, 40, 1.2),
        Product("EGGS-12", "Eggs, dozen", "dairy", "tray", "sup_fresh", 399, 285, 22, 1.6),
        Product("YOGURT-500G", "Plain yogurt 500 g", "dairy", "tub", "sup_fresh", 229, 150, 14, 1.0),
        Product("CHEESE-200G", "Cheddar 200 g", "dairy", "pack", "sup_fresh", 399, 270, 10, 1.4),
        Product("BREAD-LOAF", "Bread loaf", "bakery", "loaf", "sup_fresh", 279, 170, 35, 1.3),
        Product("BANANA-KG", "Bananas", "produce", "kg", "sup_fresh", 129, 78, 25, 1.0),
        Product("TOMATO-KG", "Tomatoes", "produce", "kg", "sup_fresh", 249, 160, 18, 1.4),
        Product("ONION-KG", "Onions", "produce", "kg", "sup_fresh", 169, 100, 16, 1.4),
        Product("APPLE-KG", "Apples", "produce", "kg", "sup_fresh", 299, 190, 15, 1.2),
        Product("CHICKEN-KG", "Chicken thighs", "meat", "kg", "sup_fresh", 699, 510, 12, 1.9),
        Product("SODA-2L", "Cola 2 L", "beverages", "bottle", "sup_fresh", 229, 135, 20, 1.6),
        Product("CHIPS-150G", "Potato chips 150 g", "snacks", "bag", "sup_fresh", 249, 140, 18, 1.5),
    ),
    suppliers=(
        Supplier("sup_ggw", "Golden Grain Wholesale", "goldengrainwholesale.example",
                 "billing@goldengrainwholesale.example", "Sam Ortega", "Meridian Trust Bank", "7702 1180 5532",
                 date(2024, 3, 1), terms_days=30, pay_lag_days=(23, 27), order_weekdays=(0,),
                 early_pay_discount_pct=0.02, early_pay_days=10, invoice_prefix="GGW", lead_days=7,
                 pack_category="staples_wholesale"),
        Supplier("sup_fresh", "FreshLine Produce & Dairy", "freshlineproduce.example",
                 "invoices@freshlineproduce.example", "Helen Brooks", "Harbor Federal Bank", "4410 8812 0937",
                 date(2023, 11, 15), terms_days=14, pay_lag_days=(11, 14), order_weekdays=(1, 4),
                 invoice_prefix="FL", pack_category="fresh_produce"),
    ),
    bills=(
        Bill("bill_rent", "Elmwood Property Management", "pay_elmwood", "rent", 1, 240_000,
             "RENT ELMWOOD PROPERTY MGMT", "3301 7720 1145"),
        Bill("bill_power", "CityGrid Power", "pay_citygrid", "utilities", 12, 34_000, "CITYGRID POWER BILL",
             "9910 0021 3384", sd_minor=2_500,
             month_factors=((4, 0.85), (5, 0.95), (6, 1.15), (7, 1.35), (8, 1.4), (9, 1.1), (10, 0.95)),
             late=((8, 6, 2_500),)),
        Bill("bill_water", "Metro Water Utility", "pay_metrowater", "utilities", 15, 6_500, "METRO WATER UTILITY",
             "9910 4410 0072", sd_minor=600),
        Bill("bill_internet", "LinkFast Broadband", "pay_linkfast", "utilities", 20, 6_500,
             "LINKFAST BROADBAND", "5520 1190 3348"),
        Bill("bill_insurance", "Shieldwell Insurance", "pay_shieldwell", "insurance", 8, 8_500,
             "SHIELDWELL INSURANCE PREMIUM", "6620 0091 7731"),
        Bill("bill_pos_a", "ShelfPOS", "pay_shelfpos", "software_subscriptions", 3, 5_900,
             "SHELFPOS PRO SUBSCRIPTION ACCT SP-20931", "8800 1123 4409"),
        # Planted duplicate POS subscription: a second ShelfPOS account opened on a tablet upgrade in June.
        Bill("bill_pos_b", "ShelfPOS", "pay_shelfpos", "software_subscriptions", 17, 5_900,
             "SHELFPOS PRO SUBSCRIPTION ACCT SP-48817", "8800 1123 4409", start=date(2026, 6, 17)),
    ),
    customers=(
        Customer("cus_sunrise", "Sunrise Cafe", "orders@sunrisecafe.example", True, 1, 30, 61_000, 6_000,
                 date(2026, 4, 1), (2, 9), unpaid=((date(2026, 8, 1), 64_280),)),
        Customer("cus_littlesteps", "Little Steps Daycare", "office@littlestepsdaycare.example", True, 15, 15,
                 38_000, 3_000, date(2026, 4, 15), (0, 6), unpaid=((date(2026, 9, 15), 38_650),)),
        Customer("cus_greenleaf", "Green Leaf Community Kitchen", "hello@greenleafkitchen.example", False, 25, 14,
                 21_400, 0, date(2026, 9, 25), (0, 3), unpaid=((date(2026, 9, 25), 21_400),)),
    ),
)

FASHION = BusinessSpec(
    id="lina_boutique",
    name="Lina's Boutique",
    pack="fashion_retail",
    ref_prefix="LB",
    owner_name="Lina Moreau",
    owner_email="lina@linasboutique.example",
    finance_email="accounts@linasboutique.example",
    domain="linasboutique.example",
    bank_name="Harbor Federal Bank",
    bank_account_number="4410 3307 2286",
    wallet_provider="PayNest Wallet",
    wallet_account_number="PN-7781-0518",
    cash_book_number="CASH-LB",
    opening_bank_minor=880_000,
    opening_cash_minor=15_000,
    cash_float_minor=15_000,
    wallet_share=0.62,
    wallet_fee_rate=0.021,
    wallet_monthly_fee_minor=1_500,
    ticket_mean_minor=5_200,
    payer_pool=210,
    weekday_factors=(0.62, 0.72, 0.82, 0.95, 1.20, 1.80, 0.92),
    day_noise_sd=0.14,
    holiday_uplift={"major_festival": 2.3, "minor_holiday": 1.4, "year_end": 1.2},
    staff_net_monthly_minor=(210_000, 120_000),
    payroll_day=28,
    owner_draw_minor=420_000,
    owner_draw_day=30,
    petty_cash=(("ALTERATIONS THREAD AND PINS", 500, 2_500), ("STEAMER REPAIR", 2_000, 5_000),
                ("WINDOW CLEANING", 1_500, 3_000)),
    petty_cash_daily_prob=0.12,
    refund_daily_prob=0.25,
    products=(
        Product("DRESS-MIDI", "Midi dress", "dresses", "piece", "sup_atelier", 7_900, 3_400, 1.6, 1.4),
        Product("JEANS-SLIM", "Slim jeans", "denim", "piece", "sup_atelier", 6_500, 2_600, 2.0, 1.2,
                cost_creep_monthly=0.022),
        Product("TOP-COTTON", "Cotton top", "tops", "piece", "sup_atelier", 3_200, 1_200, 3.0, 1.2),
        Product("KNIT-SWEATER", "Knit sweater", "knitwear", "piece", "sup_atelier", 5_800, 2_400, 1.2, 1.2,
                month_factors=((4, 0.3), (5, 0.2), (6, 0.1), (7, 0.2), (8, 0.6), (9, 1.4), (10, 1.8))),
        # Planted slow mover: one buy of 30 in May, rarely sells, never reordered.
        Product("JACKET-LINEN", "Linen summer jacket", "outerwear", "piece", "sup_atelier", 8_900, 4_100, 0.035,
                1.0, reorder=False),
        Product("BLAZER", "Tailored blazer", "outerwear", "piece", "sup_atelier", 11_000, 4_800, 0.5, 1.5),
        Product("SCARF-SILK", "Silk scarf", "accessories", "piece", "sup_mode", 2_800, 900, 2.0, 1.8),
        Product("BELT-LEATHER", "Leather belt", "accessories", "piece", "sup_mode", 3_500, 1_300, 1.0, 1.4),
        Product("EARRINGS", "Drop earrings", "jewelry", "pair", "sup_mode", 2_200, 600, 2.2, 1.9),
        Product("BAG-TOTE", "Canvas tote bag", "bags", "piece", "sup_mode", 4_800, 1_900, 0.9, 1.6),
        Product("SOCKS-3PK", "Socks 3-pack", "basics", "pack", "sup_mode", 1_200, 400, 2.5, 1.0),
    ),
    suppliers=(
        Supplier("sup_atelier", "Atelier Threads Apparel", "atelierthreads.example", "ar@atelierthreads.example", "",
                 "Meridian Trust Bank", "7702 3349 1820", date(2023, 6, 1), terms_days=30, pay_lag_days=(26, 30),
                 order_month_days=(2, 16), invoice_prefix="ATC", lead_days=7, pack_category="apparel_stock",
                 fixed_orders=((date(2026, 5, 4), "JACKET-LINEN", 30),)),
        Supplier("sup_mode", "Mode Accessories Ltd", "modeaccessories.example", "billing@modeaccessories.example",
                 "", "Harbor Federal Bank", "4410 6623 0418", date(2024, 1, 10), terms_days=15,
                 pay_lag_days=(13, 15), order_weekdays=(2,), invoice_prefix="MAL", lead_days=3,
                 pack_category="accessories_stock"),
    ),
    bills=(
        Bill("bill_rent", "Larkspur Retail Holdings", "pay_larkspur", "rent", 1, 320_000,
             "RENT LARKSPUR RETAIL HOLDINGS", "3301 9045 2271"),
        Bill("bill_power", "CityGrid Power", "pay_citygrid", "utilities", 12, 18_000, "CITYGRID POWER BILL",
             "9910 0021 7720", sd_minor=1_800,
             month_factors=((4, 0.9), (5, 1.0), (6, 1.15), (7, 1.3), (8, 1.3), (9, 1.05), (10, 0.95))),
        Bill("bill_water", "Metro Water Utility", "pay_metrowater", "utilities", 15, 3_200, "METRO WATER UTILITY",
             "9910 4410 1185", sd_minor=300),
        Bill("bill_internet", "LinkFast Broadband", "pay_linkfast", "utilities", 20, 6_500,
             "LINKFAST BROADBAND", "5520 1190 7702"),
        Bill("bill_insurance", "Shieldwell Insurance", "pay_shieldwell", "insurance", 8, 11_000,
             "SHIELDWELL INSURANCE PREMIUM", "6620 0091 3318"),
        Bill("bill_pos", "ShelfPOS", "pay_shelfpos", "software_subscriptions", 3, 5_900,
             "SHELFPOS PRO SUBSCRIPTION ACCT SP-61204", "8800 1123 4409"),
        Bill("bill_social_a", "Lookbook Social", "pay_lookbook", "software_subscriptions", 9, 2_900,
             "LOOKBOOK SOCIAL SCHEDULER SUBSCRIPTION LS-1180", "8800 5521 0093"),
        # Planted duplicate subscription: a second Lookbook seat billed since July.
        Bill("bill_social_b", "Lookbook Social", "pay_lookbook", "software_subscriptions", 22, 2_900,
             "LOOKBOOK SOCIAL SCHEDULER SUBSCRIPTION LS-2297", "8800 5521 0093", start=date(2026, 7, 22)),
    ),
    customers=(
        Customer("cus_harborlane", "Harbor Lane Hotel", "procurement@harborlanehotel.example", True, 20, 30,
                 94_000, 0, date(2026, 6, 20), (3, 8), unpaid=((date(2026, 8, 20), 118_000),)),
        Customer("cus_bloom", "Bloom Events", "accounts@bloomevents.example", True, 21, 14, 24_000, 2_000,
                 date(2026, 7, 21), (0, 5), unpaid=((date(2026, 9, 21), 26_000),)),
    ),
)

BUSINESSES = (GROCERY, FASHION)

# Email domains of bill payees (for the sentinel's known-domain list and the mailbox senders).
PAYEE_DOMAINS = {
    "pay_elmwood": "elmwoodpm.example",
    "pay_citygrid": "citygridpower.example",
    "pay_metrowater": "metrowater.example",
    "pay_linkfast": "linkfast.example",
    "pay_shieldwell": "shieldwell.example",
    "pay_shelfpos": "shelfpos.example",
    "pay_larkspur": "larkspurretail.example",
    "pay_lookbook": "lookbooksocial.example",
}
