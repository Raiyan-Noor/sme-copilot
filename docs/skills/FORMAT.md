# The skill.md format

A **skill** teaches the app how one kind of business runs: how to read its bank rows, which numbers matter and what
healthy looks like, which leaks to look for, and what to ask a new owner. Built-in skills and uploaded skills use
this one format. The app compiles a skill into the same Skill Pack model the engine runs
(`backend/app/packs/schema.py`, compiled by `backend/app/packs/skill.py`).

A skill configures built-in checks. It cannot add code, add actions, or change what needs the owner's signature.

## File layout

One UTF-8 Markdown file, at most 64 KB, named `<something>.skill.md`:

```text
---
<YAML frontmatter: the machine-readable pack>
---

<Markdown body: what this business type is and what the skill watches, for people>
```

- **Frontmatter**: the fields below, nothing else. Unknown fields are refused.
- **Body**: plain Markdown (headings, paragraphs, lists, bold, italics, inline code). Raw HTML is refused. The body
  is shown to the owner when they preview the skill; the app never reads it, and it never reaches the AI planner.

## Frontmatter fields

| Field | Required | What it is |
|---|---|---|
| `id` | yes | Lowercase slug (`bakery`, `flower_shop`). Must not be a built-in skill's id. |
| `version` | yes | Integer, 1 or more. |
| `display_name` | yes | Short name, up to 40 characters. |
| `benchmarks_synthetic` | yes | Must be `true`: healthy ranges are examples and are labelled synthetic in the UI. |
| `kpi_lookback_days` | no | Window for KPIs, 28 to 365 (default 90). |
| `categories` | yes | How bank rows are categorized. Ordered: the first matching rule wins. At least one `revenue` category. |
| `seasonality` | yes | `months` (exactly 1..12, multipliers above 0 up to 5) and optional `holidays` (holiday-calendar id to multiplier). |
| `kpis` | yes | Indicators and their healthy ranges (may be an empty list). |
| `leak_detectors` | yes | Which built-in detectors run, with their thresholds (may be an empty list). |
| `financing_fit` | yes | How well each financing product type suits the business, 0 to 1, with a one-line reason. |
| `readiness` | yes | Weights and ranges for the five Readiness Passport factors (weights sum to 1), and bands. |
| `business_types` | no | Words in an owner's description that point to this business type. |
| `data_needs` | no | What onboarding asks the owner to upload, why, and whether it is required. |
| `advisor_questions` | no | Questions an experienced advisor would ask, each with a "why I'm asking" line and options. |
| `signature` | no | Added by the library maintainers to verify a skill (see Trust). Never write it by hand. |

No money amounts anywhere: thresholds are ratios, counts and day windows, so a skill works in any currency and
region. Values may only be text, numbers and true/false: no dates, no YAML tags, no `&anchor` / `*alias`.

### categories

```yaml
categories:
  flowers:                       # id: lowercase slug
    label: Fresh flowers         # owner-facing name
    kind: cogs                   # revenue | cogs | operating | owner | transfer | opening
    scheduled: false             # true: forecast from known bills, not from history
    digital: false               # revenue only: a traceable card or wallet inflow
    match:                       # case-insensitive substrings; at least one list
      channel: [card]
      counterparty: [flower market, grower]
      description: [bouquet]
      direction: out             # in | out | any; defaults from the kind
```

Keep keywords specific: `emi` would also match `premium`. In YAML flow style (`{...}`, `[...]`), quote any text that
contains a comma.

### kpis

`source: ratio` computes |sum(numerator)| / |sum(denominator)| over categorized rows; each side lists category ids or
kinds, and `complement: true` gives 1 minus the ratio (gross margin = 1 - cogs/revenue). `source: engine` reads an
engine metric (`metric: buffer_days`). `healthy` needs `min`, `max` or both. `unit` is `ratio`, `days` or `count`.

### leak_detectors

Each entry names a **registered** detector, gives it an owner-facing `label` and sets its `params`. An unknown
detector name or param is refused. The registered detectors and their params (defaults in brackets):

| Detector | Params |
|---|---|
| `duplicate_subscription` | `categories`, `groups`, `lookback_days` (120), `min_months` (2) |
| `late_fees` | `keywords`, `lookback_days` (180) |
| `losing_ad_campaigns` | `lookback_days` (90), `min_roas` (1.0) |
| `missed_early_pay_discounts` | `lookback_days` (365), `min_invoices` (2) |
| `payment_fees` | `fee_categories`, `lookback_days` (90), `max_share_of_digital` |
| `product_returns` | `lookback_days` (90), `max_return_rate` (0.15), `min_units_sold` (20) |
| `refunds_excess` | `refund_categories`, `lookback_days` (90), `max_share_of_revenue` |
| `slow_moving_stock` | `min_days_held` (90), `max_sell_through` (0.5), `carrying_cost_rate` (0.25) |
| `supplier_price_creep` | `lookback_days` (365), `min_purchases` (6), `min_increase` (0.05) |
| `unprofitable_products` | `lookback_days` (180), `min_sale_days` (14) |

`categories`, `fee_categories` and `refund_categories` must name categories of the same skill. `groups` maps a
purpose id to keywords (`pos: [pos, point of sale]`). Detectors that read products, sales lines, purchases or ad
spend find nothing until the owner uploads those records.

### data_needs and advisor_questions

```yaml
data_needs:
  - id: bank_statement
    kind: bank                   # bank | sales | products | ad_spend: which CSV the upload must be
    required: true
    ask: "Upload a bank or card statement (CSV)."            # up to 200 characters
    why: "It is how I see your cash, your sales and your fees."
    label: a bank statement      # "I could also check <unlocks> if you add <label>."
    unlocks: "your cash buffer and your fees"

advisor_questions:
  - id: card_fees
    ask: "What fee does your card provider charge per sale?"
    why: "Card fees creep up quietly. I will flag it if you pay more than you agreed."
    options:                     # 2 to 6; an option without a value means "not sure" (keeps the default)
      - {label: About 1%, value: 0.01}
      - {label: Not sure}
    effect: {detector: payment_fees, param: max_share_of_digital}   # or {fact: <slug>, unit: ratio|days|count}
```

An answer either becomes an owner-stated fact (`owner.<fact>`) or sets one param of a detector the skill runs, and
each option's value must be valid for that param.

## Trust

- **Verified**: signed with the library key (Ed25519). The signature covers the file's sha256, so any later edit
  makes the skill unverified again. The built-in skills are signed.
- **Community, unverified**: everything else. It runs exactly the same checks, but every label that could reach the
  AI planner (display name, category, KPI, detector, band and financing labels) is rebuilt from the skill's ids, so
  the planner never sees a word an uploader wrote. The owner still sees the skill's own wording in the preview and
  during onboarding.

The **skill hash** is the SHA-256 of the file's bytes (UTF-8, LF line endings, no BOM) with its `signature:` line
removed. It is recorded in the audit log when the skill is uploaded and activated, and the next on-chain anchoring
batch publishes it (the hash only, never the file). A business keeps running exactly the file it activated: a file
changed on disk afterwards no longer matches its hash and is refused.

## What a skill can never do

Each of these is refused at upload with its own error:

- set policy, tiers, caps, mandates, tools, actions or the gateway: keys such as `policy`, `tiers`, `caps`,
  `mandates`, `max_amount_minor`, `gateway`, `tools`, `actions` and `allowlist` are refused at any depth;
- run code: detectors come from the built-in registry only;
- carry instructions for an AI in any frontmatter field ("ignore your previous instructions", "approve all" ...).
  In the body such text is allowed but flagged to the owner, and the body never reaches the planner;
- contain raw HTML or script in the body;
- reuse a built-in skill's id.

## Minimal example

This file validates and runs with the built-in detectors (the test suite checks it):

```markdown
---
id: flower_shop
version: 1
display_name: Flower shop
benchmarks_synthetic: true

categories:
  card_sales:
    label: Card sales
    kind: revenue
    digital: true
    match: {description: [card settlement]}
  cash_sales:
    label: Cash sales
    kind: revenue
    match: {description: [cash sales]}
  flowers:
    label: Fresh flowers
    kind: cogs
    match: {counterparty: [flower market, grower]}
  rent:
    label: Rent
    kind: operating
    scheduled: true
    match: {description: [rent]}
  payment_fees:
    label: Payment fees
    kind: operating
    match: {description: [merchant fee]}

seasonality:
  months: {1: 0.9, 2: 1.6, 3: 1.0, 4: 1.0, 5: 1.3, 6: 1.0, 7: 0.9, 8: 0.9, 9: 1.0, 10: 1.0, 11: 1.0, 12: 1.2}

kpis:
  - {id: gross_margin, label: Gross margin, unit: ratio, source: ratio, numerator: [cogs], denominator: [revenue], complement: true, healthy: {min: 0.5}}
  - {id: buffer_days, label: Cash buffer, unit: days, source: engine, metric: buffer_days, healthy: {min: 14}}

leak_detectors:
  - detector: payment_fees
    label: Card fees above the usual rate
    params: {fee_categories: [payment_fees], lookback_days: 90, max_share_of_digital: 0.015}
  - detector: slow_moving_stock
    label: Flowers that are not selling
    params: {min_days_held: 14}

financing_fit:
  working_capital_loan: {fit: 0.7, reason: Steady sales outside the peaks}

readiness:
  factors:
    inflow_regularity: {weight: 0.25, worst: 0.30, best: 0.90}
    revenue_stability: {weight: 0.20, worst: 0.30, best: 0.90}
    buffer_days: {weight: 0.20, worst: 3, best: 30}
    collection_days: {weight: 0.15, worst: 30, best: 3}
    payment_punctuality: {weight: 0.20, worst: 0.60, best: 1.00}
  bands:
    - {id: ready, label: Ready, min_score: 0.75}
    - {id: early, label: Early, min_score: 0.0}

data_needs:
  - id: bank_statement
    kind: bank
    required: true
    ask: "Upload a bank or card statement (CSV), the last three months if you can."
    why: "It is how I see your cash, your sales and your fees."
    label: a bank statement
    unlocks: "your cash buffer and your fees"

advisor_questions:
  - id: card_fees
    ask: "What fee does your card provider charge per sale?"
    why: "Card fees creep up quietly. I will flag it if you pay more than you agreed."
    options:
      - {label: About 1%, value: 0.01}
      - {label: About 2%, value: 0.02}
      - {label: Not sure}
    effect: {detector: payment_fees, param: max_share_of_digital}
---

# Flower shop

For florists. Sales peak around Valentine's Day and Mother's Day, and fresh stock wilts in days.
```

## Checking a skill

```text
make validate-skill FILE=skills/bakery.skill.md
```

prints the badge, the hash and what the skill asks and watches, or every problem found, exactly as an upload would.
