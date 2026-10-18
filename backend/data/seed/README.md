# Seed data

`make seed` runs `generate.py` and writes deterministic, clearly synthetic data to `backend/data/generated/`
(gitignored). Tests call `data.seed.generate.generate(tmp_path)` directly (about 2 s), so CI needs no `make seed`.

| File | What |
|---|---|
| `businesses.py` | Both businesses as data: products, suppliers, bills, staff pay, credit customers, planted quirks |
| `holidays.yaml` | Holiday calendar config: `id` is the pack seasonality key, `start`..`end` the shopping window |
| `transactions.py` | Six months of bank, wallet and cash statements, POS sale lines, purchases, receivables, schedule |
| `anomalies.py` | Ledger-side manifest entries, computed from the generated data |
| `mailbox.py` | Maya's 30-email finance mailbox: legitimate mail and six planted attacks |
| `pdf.py`, `png.py` | Dependency-free, byte-stable PDF invoices and receipt images |

Window: 2026-04-19 .. 2026-10-18; simulated today 2026-10-19, the week before the Harvest Festival.

**Manifest** (`generated/manifest.json`, test-only ground truth, never read by app code): `anomalies[]` lists every
planted item with `facts`, `evidence` (statement `reference`s, row IDs, or a file + filter) and
`expected_detection`. `mailbox.emails[]` gives each email's category, `expected_flags` (from `flag_vocabulary`)
and extracted-field ground truth. `files` holds a SHA-256 of every output file.

**Planted:** rice price creep, duplicate ShelfPOS subscription, wallet fees, a below-cost product, missed
early-pay discounts, a late fee, three overdue dues (one within the T2 reminder cap, one over it, one not
allow-listed), holiday spikes, next payroll and rent. Lina's Boutique adds denim price creep, a duplicate
scheduler subscription, a slow-moving jacket and two overdue dues. Mailbox attacks: lookalike-domain
bank-detail change, urgent "owner" transfer, PDF invoice with hidden instructions, manipulated receipt total,
goal-hijack email, duplicate invoice resend.

**Determinism:** fixed numpy seeds, Faker pinned (`pyproject.toml`) and seeded per instance, no wall clock, LF
endings, fixed MIME boundaries, uncompressed PDF/PNG streams. Changing any of this changes the bytes that the
extractor's replay cache is keyed on.
