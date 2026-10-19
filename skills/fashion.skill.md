---
# Skill Pack: fashion retail (clothing boutique). Format: docs/skills/FORMAT.md.
# All benchmarks below are synthetic, chosen for the demo, and labelled as such in the UI.
# No money amounts here: thresholds are ratios, counts and day windows (currency- and region-neutral).
id: fashion_retail
version: 1
display_name: Fashion
benchmarks_synthetic: true
kpi_lookback_days: 90

# Ordered: the first matching rule wins. Moves between the business's own accounts come first so they never count
# as revenue. Revenue rules match inflows, transfers both directions, the rest outflows unless `direction` says
# otherwise. Keep keywords specific: "emi" would also match "premium".
categories:
  internal_transfer:
    label: Moves between own accounts
    kind: transfer
    match:
      channel: [internal_transfer]
      description: [paynest settlement, settlement to bank, cash deposit branch, deposit to bank, transfer between own accounts]
  sales_wallet:
    label: Mobile wallet sales
    kind: revenue
    digital: true
    match: {counterparty: [wallet customer], description: [payment received, qr payment]}
  sales_card:
    label: Card sales
    kind: revenue
    digital: true
    match: {description: [card settlement, card sales, acquirer]}
  sales_online:
    label: Online shop sales
    kind: revenue
    digital: true
    match: {description: [online order, marketplace payout, web shop]}
  sales_cash:
    label: Cash sales
    kind: revenue
    match: {description: [cash sales, z-report, till takings]}
  # Credit customers paying invoices. Scheduled: open receivables reach the forecast from scheduled items, so
  # their history stays out of the weekday baseline. Not `digital`: bank transfers carry no payment fees.
  customer_invoice:
    label: Customer invoice payments
    kind: revenue
    scheduled: true
    match: {description: [transfer from, invoice payment]}
  apparel_stock:
    label: Clothing stock
    kind: cogs
    match: {counterparty: [apparel, garment, textile, fabric, clothing, fashion house], description: [garments, apparel, fabric, collection order]}
  accessories_stock:
    label: Accessories and footwear
    kind: cogs
    match: {counterparty: [accessor, jewel, footwear, shoe, leather], description: [accessories, footwear]}
  rent:
    label: Rent
    kind: operating
    scheduled: true
    match: {counterparty: [landlord, property, properties, realty], description: [rent]}
  payroll:
    label: Staff wages
    kind: operating
    scheduled: true
    match: {description: [payroll, salary, wages]}
  late_fees_penalties:
    label: Late fees and penalties
    kind: operating
    match: {description: [late fee, late payment, penalty]}
  insurance:
    label: Insurance
    kind: operating
    scheduled: true
    match: {counterparty: [insurance], description: [insurance]}
  utilities:
    label: Power, water and internet
    kind: operating
    scheduled: true
    match:
      counterparty: [electric, power, water, utility, broadband, internet, telecom]
      description: [electricity, water bill, utility, broadband, internet]
  payment_fees:
    label: Payment fees
    kind: operating
    match: {description: [merchant fee, merchant service fee, platform fee, transaction fee, processing fee, settlement fee, wallet fee, mdr]}
  software_subscriptions:
    label: Software subscriptions
    kind: operating
    scheduled: true
    match: {counterparty: [pos system, point of sale, software, cloud], description: [subscription, scheduler, pos plan, monthly plan]}
  # Kind revenue so P&L reports net revenue (refund outflows reduce it) and a refund spike stays out of opex KPIs.
  customer_refunds:
    label: Customer refunds and returns
    kind: revenue
    match: {direction: out, channel: [refund], description: [refund, return to customer, exchange difference]}
  tailoring:
    label: Alterations and tailoring
    kind: operating
    match: {counterparty: [tailor], description: [alteration, tailoring]}
  marketing:
    label: Marketing and photo shoots
    kind: operating
    match: {description: [boost, ads, promotion, photoshoot, influencer]}
  repairs_maintenance:
    label: Repairs and upkeep
    kind: operating
    match: {description: [repair, steamer]}
  packaging:
    label: Bags and packaging
    kind: operating
    match: {description: [packaging, carrier bags, paper bags, gift box]}
  shop_running:
    label: Cleaning and petty cash
    kind: operating
    match: {description: [cleaning, supplies, petty cash]}
  owner_drawings:
    label: Owner drawings
    kind: owner
    match: {description: [owner drawings, owner draw, owner savings, personal withdrawal]}
  loan_repayment:
    label: Loan repayments
    kind: transfer
    scheduled: true
    match: {direction: out, description: [loan repayment, loan installment]}

# Fashion is far more seasonal than grocery: festival and new-season peaks, end-of-season lulls.
seasonality:
  months: {1: 0.85, 2: 0.80, 3: 1.00, 4: 1.10, 5: 0.95, 6: 0.85, 7: 0.80, 8: 0.90, 9: 1.05, 10: 1.15, 11: 1.20, 12: 1.30}
  holidays:
    major_festival: 2.30
    minor_holiday: 1.40
    year_end: 1.20

kpis:
  - {id: gross_margin, label: Gross margin, unit: ratio, source: ratio, numerator: [cogs], denominator: [revenue], complement: true, healthy: {min: 0.45, max: 0.65}}
  - {id: rent_share, label: Rent as share of sales, unit: ratio, source: ratio, numerator: [rent], denominator: [revenue], healthy: {max: 0.15}}
  - {id: payroll_share, label: Wages as share of sales, unit: ratio, source: ratio, numerator: [payroll], denominator: [revenue], healthy: {max: 0.18}}
  - {id: payment_fee_share, label: Payment fees as share of digital sales, unit: ratio, source: ratio, numerator: [payment_fees], denominator: [sales_wallet, sales_card, sales_online], healthy: {max: 0.02}}
  - {id: refund_share, label: Refunds as share of sales, unit: ratio, source: ratio, numerator: [customer_refunds], denominator: [revenue], healthy: {max: 0.08}}
  - {id: digital_share, label: Digital share of sales, unit: ratio, source: ratio, numerator: [sales_wallet, sales_card, sales_online], denominator: [revenue], healthy: {min: 0.50}}
  - {id: buffer_days, label: Cash buffer, unit: days, source: engine, metric: buffer_days, healthy: {min: 30, max: 120}}

# Ledger detectors read categorized statement rows; supplier_price_creep, missed_early_pay_discounts and
# slow_moving_stock read the business's purchase lines, unprofitable_products its point-of-sale lines.
leak_detectors:
  - detector: duplicate_subscription
    label: Paying twice for the same software
    params:
      categories: [software_subscriptions]
      groups: {pos: [pos, point of sale], bookkeeping: [bookkeeping, accounting], social: [social, scheduler], design: [design, photo editing]}
      lookback_days: 120
      min_months: 2
  - detector: payment_fees
    label: Payment fees above the usual rate
    params: {fee_categories: [payment_fees], lookback_days: 90, max_share_of_digital: 0.02}
  - detector: refunds_excess
    label: Refunds above the usual rate
    params: {refund_categories: [customer_refunds], lookback_days: 90, max_share_of_revenue: 0.08}
  - detector: late_fees
    label: Late fees and penalties paid
    params: {keywords: [late fee, late payment, penalty], lookback_days: 180}
  - detector: supplier_price_creep
    label: Supplier raising unit prices
    params: {lookback_days: 365, min_purchases: 4, min_increase: 0.05}
  - detector: unprofitable_products
    label: Product sold below cost
    params: {lookback_days: 180, min_sale_days: 7}
  - detector: missed_early_pay_discounts
    label: Early-payment discounts missed
    params: {lookback_days: 365, min_invoices: 2}
  - detector: slow_moving_stock
    label: Stock that is not selling
    params: {min_days_held: 90, max_sell_through: 0.4, carrying_cost_rate: 0.25}
  - detector: losing_ad_campaigns
    label: Ad campaign costing more than it earns
    params: {lookback_days: 90, min_roas: 1.0}
  - detector: product_returns
    label: Product coming back too often
    params: {lookback_days: 90, max_return_rate: 0.15, min_units_sold: 20}

# Ranking input for the financing matcher; eligibility stays with each product's own rules.
financing_fit:
  inventory_financing: {fit: 0.85, reason: Seasonal stock buys ahead of peaks suit stock-backed financing}
  working_capital_loan: {fit: 0.75, reason: Bridges the gap between buying stock and the selling season}
  nano_loan: {fit: 0.60, reason: Small amounts help with top-up orders}
  overdraft: {fit: 0.60, reason: Covers short gaps in slow months}
  merchant_cash_advance: {fit: 0.50, reason: Repayments flex with lumpy seasonal sales but cost more}
  equipment_lease: {fit: 0.30, reason: Little equipment beyond fittings and displays}
  invoice_financing: {fit: 0.20, reason: Few invoices; most customers pay at purchase}

readiness:
  factors:
    inflow_regularity: {weight: 0.15, worst: 0.20, best: 0.80}
    revenue_stability: {weight: 0.15, worst: 0.20, best: 0.80}
    buffer_days: {weight: 0.30, worst: 10, best: 60}
    collection_days: {weight: 0.15, worst: 45, best: 7}
    payment_punctuality: {weight: 0.25, worst: 0.60, best: 1.00}
  bands:
    - {id: ready, label: Ready, min_score: 0.70}
    - {id: building, label: Building, min_score: 0.45}
    - {id: early, label: Early, min_score: 0.0}

# Onboarding: words in the owner's own description that pick this pack.
business_types: [clothing, clothes, fashion, boutique, apparel, garment, dress, shoe, footwear, accessories, tailor, saree, textile]

# What onboarding asks for, one at a time. The owner can upload, or skip; a skipped item shows in the brief as
# "I could also check <unlocks> if you add <label>".
data_needs:
  - id: bank_statement
    kind: bank
    required: true
    ask: "Upload a bank or mobile-wallet statement (CSV), the last three months if you can."
    why: "It is how I see your cash, every sale, bill and fee, and how many days your cash would last."
    label: a bank or wallet statement
    unlocks: "your cash buffer and the leaks hiding in your bills"
  - id: products
    kind: products
    required: true
    ask: "Upload your product list with cost price, sale price and stock (CSV from your shop system or a spreadsheet)."
    why: "In fashion the margin is made or lost per piece: markdowns, returns and slow sizes all hide in the total."
    label: your product list
    unlocks: "margins per product and stock that is about to run out"
  - id: product_sales
    kind: sales
    required: false
    ask: "Upload your sales per product (date, product, quantity, amount). Three months is plenty."
    why: "Sales per product show what actually sells, what comes back as returns, and what sits on the rail."
    label: your sales per product
    unlocks: "your best and worst sellers and which products come back as returns"
  - id: ad_spend
    kind: ad_spend
    required: true
    ask: "Do you run Facebook, Instagram or Google ads? If so, upload your ad spend export so I can check they are paying off."
    why: "Ads that do not pay for themselves are one of the most common hidden costs for a shop that sells online."
    label: your ad spend export
    unlocks: "whether each ad campaign is paying for itself"

# What an experienced fashion advisor asks, which owners often do not think of. Each answer becomes an owner-stated
# fact or a detector setting for this business (packs/answers.py). Option labels are UI text for the owner.
advisor_questions:
  - id: return_rate
    ask: "Do you take returns? Roughly what share of what you sell comes back?"
    why: "Returns quietly eat fashion margins. I will flag any product that comes back more often than you expect."
    options:
      - {label: Exchanges only, value: 0.05}
      - {label: Under 10%, value: 0.10}
      - {label: 10 to 20%, value: 0.20}
      - {label: More than 20%, value: 0.30}
      - {label: Not sure}
    effect: {detector: product_returns, param: max_return_rate}
  - id: festival_stock
    ask: "Do you buy extra stock ahead of big festivals and season changes (Eid, Christmas, Diwali, year-end sales)?"
    why: "Festival stock sits for weeks before it sells, so I will not call it slow-moving too early."
    options:
      - {label: "Yes, well ahead", value: 150}
      - {label: A little, value: 120}
      - {label: "No", value: 90}
      - {label: Not sure}
    effect: {detector: slow_moving_stock, param: min_days_held}
  - id: marketplace_fees
    ask: "Do you sell through online marketplaces? What commission do they take?"
    why: "Marketplace commissions come out before the money reaches you, so they hide inside your sales figure."
    options:
      - {label: I do not use marketplaces, value: 0}
      - {label: About 10%, value: 0.10}
      - {label: About 15%, value: 0.15}
      - {label: About 20% or more, value: 0.20}
      - {label: Not sure}
    effect: {fact: marketplace_commission, unit: ratio}
  - id: supplier_terms
    ask: "How many days do your suppliers give you to pay?"
    why: "Credit terms decide how long your cash can work for you before a bill is due."
    options:
      - {label: I pay upfront, value: 0}
      - {label: About a week, value: 7}
      - {label: About two weeks, value: 15}
      - {label: About a month, value: 30}
      - {label: Two months, value: 60}
      - {label: Not sure}
    effect: {fact: supplier_terms_days, unit: days}
signature: "ed25519:FX+aW/ycTcw3WabpVg5y+X1L3OWqq47NLbW/CDeM+z76vnsqo+JGAmT1U3mPzHU3I4ukZZK5MBWVJ231DpdOBw=="
---

# Fashion

For clothing boutiques, shoe and accessory shops and tailors: shops whose stock is seasonal, whose sales peak around
festivals, and who often sell online and through marketplaces as well as in store.

## What this skill watches

- **Returns.** Returns quietly eat fashion margins. The skill flags products that come back more than the rate you
  told it is normal.
- **Ad campaigns.** Return on ad spend per campaign and channel, and campaigns that cost more than they bring in.
- **Seasonal and slow stock.** Stock bought for a season that does not sell through.
- **Margins per product, supplier prices and payment terms.** Products sold below cost, unit prices that creep up,
  and early-payment discounts missed.
- **Fees and bills.** Card, wallet and marketplace fees, refunds above normal, duplicate software and late fees.

## What it asks you

Your bank or wallet statement and your product list (both needed), sales per product and ad spend (optional), and
the questions an experienced fashion advisor would ask: returns, festival stock, marketplace commissions and
supplier credit terms.

Benchmarks in this skill are synthetic and labelled as such.
