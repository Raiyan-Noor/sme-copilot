---
# Community skill: bakery (bread, pastries, cakes). Format: docs/skills/FORMAT.md.
# Not signed by the library key, so it shows as "Community, unverified". It uses built-in detectors only.
# All benchmarks below are synthetic, chosen as an example, and labelled as such in the UI.
id: bakery
version: 1
display_name: Bakery
benchmarks_synthetic: true
kpi_lookback_days: 90

categories:
  internal_transfer:
    label: Moves between own accounts
    kind: transfer
    match:
      channel: [internal_transfer]
      description: [settlement to bank, cash deposit branch, deposit to bank, transfer between own accounts]
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
  sales_cash:
    label: Counter sales (cash)
    kind: revenue
    match: {description: [cash sales, z-report, till takings]}
  cake_orders:
    label: Cake and catering orders
    kind: revenue
    match: {description: [cake order, catering, custom order, order deposit]}
  wholesale_accounts:
    label: Cafe and shop accounts
    kind: revenue
    scheduled: true
    match: {description: [transfer from, invoice payment]}
  flour_grain:
    label: Flour and grain
    kind: cogs
    match: {counterparty: [flour, mill, grain], description: [flour, semolina]}
  dairy_eggs:
    label: Butter, milk and eggs
    kind: cogs
    match: {counterparty: [dairy, creamery, egg, poultry], description: [butter, milk, cream, eggs]}
  other_ingredients:
    label: Sugar, yeast and other ingredients
    kind: cogs
    match: {counterparty: [sugar, wholesale, distributor, trading, confectioner], description: [sugar, yeast, chocolate, ingredients]}
  rent:
    label: Rent
    kind: operating
    scheduled: true
    match: {counterparty: [landlord, property, properties, realty], description: [rent]}
  payroll:
    label: Bakers and counter staff
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
    label: Gas, power and water
    kind: operating
    scheduled: true
    match:
      counterparty: [electric, power, gas supply, water, utility, broadband, internet, telecom]
      description: [electricity, gas bill, water bill, utility, broadband, internet]
  payment_fees:
    label: Payment fees
    kind: operating
    match: {description: [merchant fee, merchant service fee, platform fee, transaction fee, processing fee, settlement fee, wallet fee, mdr]}
  software_subscriptions:
    label: Software subscriptions
    kind: operating
    scheduled: true
    match: {counterparty: [pos system, point of sale, software, cloud], description: [subscription, pos plan, monthly plan]}
  oven_maintenance:
    label: Oven and mixer repairs
    kind: operating
    match: {description: [oven, mixer, proofer, repair, refrigerat]}
  unsold_disposal:
    label: Unsold bake and waste disposal
    kind: operating
    match: {description: [waste collection, disposal, unsold]}
  packaging:
    label: Boxes and bags
    kind: operating
    match: {description: [packaging, cake box, paper bags]}
  shop_running:
    label: Cleaning and supplies
    kind: operating
    match: {description: [cleaning, supplies, petty cash]}
  owner_drawings:
    label: Owner drawings
    kind: owner
    match: {description: [owner drawings, owner draw, personal withdrawal]}
  loan_repayment:
    label: Loan repayments
    kind: transfer
    scheduled: true
    match: {direction: out, description: [loan repayment, loan installment]}

# Cakes make festivals and the year end the busiest days of a bakery.
seasonality:
  months: {1: 0.95, 2: 1.00, 3: 0.98, 4: 1.00, 5: 1.00, 6: 0.96, 7: 0.95, 8: 0.96, 9: 1.00, 10: 1.02, 11: 1.05, 12: 1.20}
  holidays:
    major_festival: 2.20
    minor_holiday: 1.40
    year_end: 1.30

kpis:
  - {id: gross_margin, label: Gross margin, unit: ratio, source: ratio, numerator: [cogs], denominator: [revenue], complement: true, healthy: {min: 0.55, max: 0.75}}
  - {id: rent_share, label: Rent as share of sales, unit: ratio, source: ratio, numerator: [rent], denominator: [revenue], healthy: {max: 0.10}}
  - {id: payroll_share, label: Wages as share of sales, unit: ratio, source: ratio, numerator: [payroll], denominator: [revenue], healthy: {max: 0.30}}
  - {id: payment_fee_share, label: Payment fees as share of digital sales, unit: ratio, source: ratio, numerator: [payment_fees], denominator: [sales_wallet, sales_card], healthy: {max: 0.015}}
  - {id: waste_share, label: Waste disposal as share of ingredients bought, unit: ratio, source: ratio, numerator: [unsold_disposal], denominator: [cogs], healthy: {max: 0.05}}
  - {id: digital_share, label: Digital share of sales, unit: ratio, source: ratio, numerator: [sales_wallet, sales_card], denominator: [revenue], healthy: {min: 0.30}}
  - {id: buffer_days, label: Cash buffer, unit: days, source: engine, metric: buffer_days, healthy: {min: 14, max: 45}}

leak_detectors:
  - detector: duplicate_subscription
    label: Paying twice for the same software
    params:
      categories: [software_subscriptions]
      groups: {pos: [pos, point of sale], bookkeeping: [bookkeeping, accounting]}
      lookback_days: 120
      min_months: 2
  - detector: payment_fees
    label: Payment fees above the usual rate
    params: {fee_categories: [payment_fees], lookback_days: 90, max_share_of_digital: 0.015}
  - detector: late_fees
    label: Late fees and penalties paid
    params: {keywords: [late fee, late payment, penalty], lookback_days: 180}
  - detector: supplier_price_creep
    label: Ingredient supplier raising prices
    params: {lookback_days: 365, min_purchases: 6, min_increase: 0.05}
  - detector: unprofitable_products
    label: Bake sold below its ingredient cost
    params: {lookback_days: 180, min_sale_days: 14}
  - detector: missed_early_pay_discounts
    label: Early-payment discounts missed
    params: {lookback_days: 365, min_invoices: 2}
  - detector: slow_moving_stock
    label: Ingredients and goods that are not selling
    params: {min_days_held: 14, max_sell_through: 0.6, carrying_cost_rate: 0.30}
  - detector: losing_ad_campaigns
    label: Ad campaign costing more than it earns
    params: {lookback_days: 90, min_roas: 1.0}

financing_fit:
  equipment_lease: {fit: 0.85, reason: Ovens and mixers are the main investment of a bakery}
  working_capital_loan: {fit: 0.75, reason: Steady daily sales support regular installments}
  nano_loan: {fit: 0.70, reason: Small amounts match ingredient restocking}
  overdraft: {fit: 0.65, reason: Covers gaps before festival orders are paid}
  inventory_financing: {fit: 0.45, reason: "Ingredients turn over in days, so there is little stock to borrow against"}
  merchant_cash_advance: {fit: 0.40, reason: Daily sweeps are costly for a small bakery}
  invoice_financing: {fit: 0.30, reason: Only useful with large cafe accounts}

readiness:
  factors:
    inflow_regularity: {weight: 0.25, worst: 0.30, best: 0.90}
    revenue_stability: {weight: 0.20, worst: 0.30, best: 0.90}
    buffer_days: {weight: 0.20, worst: 3, best: 30}
    collection_days: {weight: 0.15, worst: 30, best: 3}
    payment_punctuality: {weight: 0.20, worst: 0.60, best: 1.00}
  bands:
    - {id: ready, label: Ready, min_score: 0.75}
    - {id: building, label: Building, min_score: 0.50}
    - {id: early, label: Early, min_score: 0.0}

business_types: [bakery, bakehouse, patisserie, cake shop, bread]

data_needs:
  - id: bank_statement
    kind: bank
    required: true
    ask: "Upload a bank or mobile-wallet statement (CSV), the last three months if you can."
    why: "It is how I see your cash, every sale, ingredient bill and fee, and how many days your cash would last."
    label: a bank or wallet statement
    unlocks: "your cash buffer and the leaks hiding in your bills"
  - id: products
    kind: products
    required: true
    ask: "Upload your product list: each bread, pastry and cake with its ingredient cost, sale price and stock (CSV)."
    why: "A croissant and a wedding cake earn very different margins. The total hides the bakes that lose money."
    label: your product list
    unlocks: "the margin on every bread, pastry and cake"
  - id: product_sales
    kind: sales
    required: false
    ask: "Upload your sales per product (date, product, quantity, amount). Three months is plenty."
    why: "Daily sales per product show what to bake more of, and what you keep throwing away."
    label: your sales per product
    unlocks: "your best and worst sellers, day by day"

advisor_questions:
  - id: unsold_bake
    ask: "How much of each day's bake is usually left unsold at closing?"
    why: "Unsold bread is the biggest hidden cost in a bakery. I keep it in mind when I look at your margins."
    options:
      - {label: Almost none, value: 0.02}
      - {label: About 5%, value: 0.05}
      - {label: About 10%, value: 0.10}
      - {label: More than 15%, value: 0.20}
      - {label: Not sure}
    effect: {fact: unsold_share, unit: ratio}
  - id: cake_deposits
    ask: "Do you take cake or catering orders with a deposit up front?"
    why: "A deposit is money for work you have not done yet. I keep it apart from the cash you are free to spend."
    options:
      - {label: "No", value: 0}
      - {label: A few each month, value: 0.05}
      - {label: A big part of my sales, value: 0.25}
      - {label: Not sure}
    effect: {fact: deposit_share, unit: ratio}
  - id: ingredient_prices
    ask: "Have flour, butter or sugar prices gone up noticeably this year?"
    why: "Ingredient prices move fast. Your answer sets how quickly I flag a supplier who raises prices."
    options:
      - {label: "Yes, a lot", value: 0.03}
      - {label: A little, value: 0.05}
      - {label: "No", value: 0.08}
      - {label: Not sure}
    effect: {detector: supplier_price_creep, param: min_increase}
  - id: cafe_accounts
    ask: "Do you supply cafes or shops on account and get paid later?"
    why: "Wholesale accounts are often paid late. I will watch who owes you and for how long."
    options:
      - {label: "No", value: 0}
      - {label: Some of my sales, value: 0.10}
      - {label: Most of my sales, value: 0.50}
      - {label: Not sure}
    effect: {fact: wholesale_credit_share, unit: ratio}
  - id: wallet_fees
    ask: "What fee does your mobile wallet or card provider charge per sale?"
    why: "Payment fees creep up quietly. I will flag it if you pay more than the rate you agreed."
    options:
      - {label: About 1%, value: 0.01}
      - {label: About 1.5%, value: 0.015}
      - {label: About 2%, value: 0.02}
      - {label: Not sure}
    effect: {detector: payment_fees, param: max_share_of_digital}
---

# Bakery

For bakeries, patisseries and cake shops: businesses that bake every morning, sell most of it over the counter the
same day, and earn extra from cake and catering orders around festivals.

## What this skill watches

- **Margin per bake.** Bread, pastries and cakes earn very different margins; the skill flags anything sold below
  its ingredient cost.
- **Ingredient prices.** Flour, butter and sugar suppliers who raise their unit prices, as sensitive as you ask.
- **Waste.** Disposal costs against what you buy, and goods that are not selling.
- **Fees and bills.** Card and wallet fees above the agreed rate, duplicate software and late fees.

## What it asks you

Your bank or wallet statement and your product list (both needed), sales per product (optional), and what an
experienced bakery advisor would ask: unsold bake at closing, cake deposits, ingredient prices, cafe accounts and
payment fees.

This is a community skill: it was not signed by the library, so it shows as unverified. It only configures
built-in checks; it cannot add code or change what needs your signature.

Benchmarks in this skill are synthetic and labelled as such.
