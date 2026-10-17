# Build prompts for Claude Code

Run these in order, one per fresh session (or `/clear` between them). Each assumes `CLAUDE.md` is in the repo root.
Prompts marked ∥ can run in parallel on separate branches by different teammates. Every prompt ends the same way:
run the tests, and stop and report rather than weakening an invariant.

Times are Dhaka. Owners refer to the roles in the plan: **A** agent & safety, **D** data & finance engine,
**S** Skill Packs & analysis, **P** product, demo & docs.

---

## Day 1 · Sunday: foundations

Backend first. Prompts 0–7 must not depend on branding: nothing in `backend/` refers to the product name, logo or
colors. The frontend starts as an unbranded skeleton (8). Branding arrives from the designer at about 10:15 and is
applied in 9; nothing before that waits for it.

### 0. Backend scaffold (A, first, ~45 min)
> Read CLAUDE.md. Create the repo `sme-copilot` and scaffold the backend exactly as the Layout section describes:
> `backend/pyproject.toml` with package name `sme-copilot`; FastAPI app with health route, passcode auth middleware
> and CORS from env; empty modules with docstrings; `policy.yaml` with the four tiers from the Tiers table;
> `.env.example` (including `ANCHOR_RPC_URL`, `ANCHOR_PRIVATE_KEY`, `ANCHOR_CHAIN_ID`, `ANCHOR_BATCH_SIZE`,
> `ANCHOR_EXPLORER_URL` with placeholder values, never a real key); Makefile with every target in Commands (stubs
> are fine); Docker Compose project name `sme-copilot`; pytest config; a GitHub Actions workflow that runs
> `make test` with `LLM_REPLAY=replay` and no secrets. No frontend yet. Commit. Done when
> `make setup && make test && make dev` all work for the backend.

### 1. Seed data ∥ (D)
> Implement `backend/data/seed/generate.py`: deterministic (fixed numpy seed + Faker) six months of transactions for
> Maya's Corner Store (grocery) and Lina's Boutique (clothing). Include: mobile-wallet merchant inflows, cash sales,
> rent, staff, utilities, payment fees; two suppliers, one with steady rice price creep; a duplicate POS
> subscription; three overdue customer dues; a holiday spike configured from a holiday calendar; known upcoming
> payables (payroll, rent). Also a 30-email finance mailbox as .eml files with the planted attacks listed in the plan
> (lookalike-domain bank-detail change, urgent "owner" transfer, PDF invoice with hidden instructions, manipulated
> receipt total) plus legitimate invoices, POs, promises to pay and a loan offer. Write a `manifest.json` listing
> every planted anomaly with its expected detection, so tests can assert against it. Done when `make seed` produces
> identical output twice.

### 2. Ledger + ingestion ∥ (D)
> Implement `ledger/` (SQLite schema per tenant, CSV statement ingestion, PII tokenization of phone/ID/account
> numbers) and the `Fact` model in `firewall/` (id, value, unit, display, source_row_ids, computed_by), which the
> calculators return. Money in integer minor units. Unit tests for ingestion and tokenization.

### 3. Calculators ∥ (D)
> Implement pure engine functions returning Facts with source row IDs: P&L by period, gross and product margins,
> cash balance, buffer days, runway, and a 30/60/90-day forecast = known scheduled payables/receivables + weekday
> baseline + pack seasonality multipliers, with a simple uncertainty band. Golden-file tests against the seed data.

### 4. Numeric Firewall ∥ (D)
> Complete `firewall/`: fact store per request, `{fact:id}` renderer, and a digit check that rejects any `[0-9]`
> outside placeholders. Unit tests for the digit check, including tricky cases (unicode digits, "1st", dates).

### 5. Skill Pack loader + grocery pack ∥ (S)
> Implement `packs/` loader and `grocery_retail.yaml` per the plan's pack format, with detector functions
> registered by name. The pack must change: expense categories, seasonality inputs to the forecast, KPIs and healthy
> ranges for benchmarking, leak detectors, financing fit and readiness weights. Validate packs with Pydantic. Tests
> prove that swapping the pack changes outputs on the same ledger.

### 6. Gateway + mandates + audit (A)
> Implement `audit/` (append-only JSONL, each entry with `prev_hash`, `verify()` and `export()`), `gateway/` (policy
> engine reading `policy.yaml`: tier lookup, amount caps, frequency caps, allow-lists, expiry, unknown tools denied;
> untrusted-provenance args force T3), mandate verification with PyNaCl (Ed25519 over action + args hash + nonce +
> expiry; nonce replay store), and `executor/sandbox_bank.py` importable only by the gateway (add a test that fails
> if anything else imports it). Policy tests for every tier boundary, cap, expiry and replay. Expose the audit
> log's current head hash and store a canonical-JSON hash of every signed mandate, so anchoring (prompt 17) can
> plug in later without changes here.

### 7. FastAPI endpoints (D + A, ~1 h)
> Expose everything built so far through thin routes in `api/` with Pydantic request and response models, all
> testable from FastAPI's `/docs` (passcode via the Authorize button): businesses and Skill Pack switch; ledger
> transactions; statement upload; facts and the `explain_fact` trace; P&L, cash position and forecast; pack KPIs and
> benchmarks; gateway propose and approve (with a signed mandate) for testing; audit log, verify and export;
> simulated clock read and advance. Export `docs/openapi.json`; it is the contract the frontend mirrors. API tests
> with FastAPI's TestClient. Nothing here refers to the product name, logo or colors.

### 8. Frontend skeleton, unbranded (P, after 7)
> Create the Next.js 16 app in `frontend/` (package name `sme-copilot`) with Tailwind and shadcn/ui. Unbranded
> skeleton only, no visual design: a sidebar layout and routes for Today, Ask, Cash flow, Financing, Inbox and Trust;
> `lib/types.ts` mirrored from `docs/openapi.json`; a typed client in `lib/api.ts` calling `NEXT_PUBLIC_API_URL`;
> each page fetches its real endpoint and renders the data plainly. Set up the three branding places from CLAUDE.md:
> `styles/theme.css` defines every color, radius and font as semantic CSS variables (`--brand-primary`,
> `--brand-accent`, `--surface`, `--surface-muted`, `--border`, `--text`, `--text-muted`, `--success`, `--warning`,
> `--danger`, `--chart-1` to `--chart-5`) with neutral placeholder values, mapped into Tailwind and shadcn's variables
> in that same file; `config/app.ts` exports `APP_NAME` and `APP_TAGLINE` with obvious placeholders; and
> `components/brand/Logo.tsx` renders `<Logo />` as a text placeholder from `APP_NAME`. Every UI mention of the name
> or logo uses these. Add a branding check to `make test` and CI that fails on hex, rgb or hsl color literals outside
> the theme file and on the codename appearing in UI text. Add the frontend to `make dev` and to CI (lint + build).

### 9. Brand swap + branded screens (P, not before ~10:15, when the designer delivers)
> Branding has arrived: app name, tagline, logo file and palette. Step 1, the brand swap: change only
> `styles/theme.css` (palette into the semantic variables), `config/app.ts` (`APP_NAME`, `APP_TAGLINE`) and the logo
> asset `<Logo />` renders. Touch no other file; commit this on its own. Done when the diff contains only those three
> places and every screen shows the new brand. Step 2: build the branded screens (approval card and approval
> sheet, Morning Brief on Today, red-team panel on Trust) from the designer's Claude Design screens if ready,
> otherwise from `docs/design-brief.md`. Use only theme variables, `APP_NAME` and `<Logo />`, the API types, and
> mock data shaped like those types where the endpoint lands on Day 2 (brief, red-team results). The branding check
> must pass.

---

## Day 2 · Monday: the agent acts

Each prompt below adds its endpoints to `/docs` the same way as prompt 7 and refreshes `docs/openapi.json`.

### 10. LLM adapter (A, morning, first)
> Implement `llm/adapter.py`: one interface for chat-with-tools and structured-output calls; OpenAI primary with
> profile-based model choice (`dev`: Terra planner; `demo`: Sol planner; Terra extractor); Gemini Flash fallback via
> its OpenAI-compatible endpoint on insufficient_quota, 429, 5xx, timeout or budget exhaustion; spend tracking from
> returned usage priced via `pricing.py`, hard cap from `LLM_BUDGET_USD`; record/replay cache keyed by a hash of
> model-independent request content, written as a generic request cache so the anchoring RPC can reuse it later;
> every call logged to audit with provider, model, tokens and cost. Unit tests with fake providers for each
> fallback trigger.

### 11. Planner loop + tools (A)
> Implement `agent/`: hand-rolled loop using `prompts/planner.md`; read tools wrapping the engine (return fact IDs,
> never raw numbers); `propose_action` that calls the gateway and returns its status; Numeric Firewall applied to
> every reply (one re-prompt, then template fallback); SSE streaming endpoint for the UI. Benign tests: ten owner
> questions answered with only valid fact placeholders.

### 12. Quarantined extractor + Inbox Sentinel ∥ (A + S)
> Implement `quarantine/` using `prompts/extractor.md` with Structured Outputs bound to Pydantic schemas (email,
> invoice, receipt), including vision for receipt images. The extractor has no tools and its output reaches the
> planner only as typed, provenance-tagged fields; never raw text. Implement `sentinel/` checks: payee/bank-detail
> change vs. history, lookalike domains (rapidfuzz + homoglyph map), urgency, amount anomaly vs. payee history,
> first-time payee hold, and a generated verification call script. Due dates, POs and promises-to-pay feed the
> forecast. Tests assert every planted mailbox attack in `manifest.json` is flagged.

### 13. Financing + Readiness Passport ∥ (D)
> Implement a synthetic catalog of 6–10 financing products with machine-readable eligibility rules, a matcher that
> returns pass/fail with a reason per rule, repayment-safe sizing (max installment under a stressed forecast), and the
> Readiness Passport (inflow regularity, revenue stability, buffer days, collection days, payment punctuality →
> band, reasons, path to eligibility). Passport exports are canonical JSON with their SHA-256 hash recorded, so
> they can be anchored and verified later. `submit_loan_application` is a T3 action producing a draft application.
> Tests: one product fails a digital-history rule, the nano loan passes and is capped.

### 14. Leaks, Tier-2 actions, Morning Brief, simulated clock ∥ (S + A)
> Implement leak detectors from the packs (duplicate subscription, supplier price creep, payment fees, unprofitable
> products, missed early-pay discounts, late fees) each with yearly impact and evidence rows; the fashion pack and
> Lina's Boutique data; T2 `send_invoice_reminder` through the gateway under a standing signed mandate; `clock.py`
> fast-forward endpoint that runs the overnight job (reminders, then the brief via `prompts/brief_writer.md`).

### 15. Red-team and benign suites (A, evening)
> Build `tests/redteam/` with ≥10 attacks (goal hijack via email, hidden PDF instructions, payee swap, replayed
> mandate, expired mandate, over-cap T2, frequency abuse, request for a T4 action, digit smuggling in replies,
> untrusted amount used in an action, memory-poisoning attempt) and `tests/benign/` with ≥20 owner tasks. `make
> redteam` writes `docs/results/redteam.json` with attack success rate, task success rate and which defense caught
> each attack. Record once per provider, then replay. (The "insider rewrites the log" attack is added with
> anchoring in prompt 17.)

---

## Day 3 · Tuesday: polish and ship

### 16. Wire the Claude Design screens (P, can start Monday)
> The skeleton, theme, app config and the three branded screens from prompt 9 already exist. Port the remaining
> Claude Design screens into the skeleton without changing their visual design: replace any hex or other color
> literals in the export with the semantic variables from `styles/theme.css`, and any product name or logo with
> `APP_NAME` and `<Logo />`. Replace mock data with the typed API client from the skeleton (types mirror the backend
> Pydantic models in `frontend/lib/types.ts`). Implement: placeholder rendering of `{fact:id}` as clickable numbers
> opening the trace drawer; SSE chat; approval sheet that signs mandates in the browser with tweetnacl (key
> generated on first run, stored in IndexedDB, public key enrolled with the server); business/pack switcher;
> fast-forward button; Trust tab reading the audit log, verify endpoint and `redteam.json`. The branding check must
> pass.

### 17. Stretch 1: on-chain anchoring (A, ~3–4 h)
Monday evening if 0–16 work end to end; otherwise Tuesday morning, before any other stretch item.
> Read CLAUDE.md invariant 9. Implement `app/anchoring/`:
> - Batch leaf hashes: the current audit-log head hash, hashes of mandates signed since the last anchor, and
>   hashes of Passports exported since the last anchor.
> - Build a SHA-256 Merkle root and store a proof per leaf. Choose sorted-pair or index-based hashing and document
>   the choice, including odd-leaf handling, in the module docstring.
> - Send one 0-value self-transaction with the root in `data` using web3.py; default Sepolia, Base Sepolia via
>   `ANCHOR_CHAIN_ID`. Refuse any chain ID outside the testnet allow-list.
> - Save an `anchors` record (batch_id, merkle_root, leaves, tx_hash, chain_id, block_number, timestamp) and append
>   an audit entry for the anchor itself (its hash goes into the next batch).
> - Register `anchor` in `policy.yaml` as a T1 system tool, testnet-only and rate-capped, not in the planner's
>   registry.
> - Run it every `ANCHOR_BATCH_SIZE` audit entries (default 20), at the end of each demo scenario, and on demand
>   from an endpoint behind an "Anchor now" button. It must never block core flows: run in the background, and on
>   RPC failure queue the batch, retry with backoff and log the failure.
> - Verification: extend the verify endpoint to recompute the log locally, fetch the anchored root from the chain,
>   and report match or mismatch with a block-explorer link (`ANCHOR_EXPLORER_URL`). Add "Verify on-chain" for
>   mandates and Passports using their stored proofs, and a Passport verifier endpoint that hashes a given Passport
>   file (canonical JSON) and reports whether it matches an anchored leaf.
> - UI: add "Anchor now", explorer links and on-chain verify states to the Trust tab and to mandate and Passport
>   views, matching the existing design and using only theme variables.
> - Tests: Merkle root and proof generation and verification, including odd leaf counts; tamper tests that edit
>   one audit-log line, one mandate and one Passport field after anchoring, each expected to report a mismatch; RPC
>   mocked through the record/replay cache so CI has no network access; red-team attack "insider rewrites log and
>   recomputes hashes", expected to be caught by the anchor check.
> - Then run one manual live anchor with `make anchor` to produce real testnet tx hashes. Done when all tests pass
>   in replay mode and `docs/results/anchors.json` holds at least one real tx hash that verifies.

### 18. Stretch 2 (only if 0–17 work end to end, in this order)
> What-if Monte Carlo on the forecast → marketing ROI → expansion planner. Same invariants and tests apply.

### 19. Evidence and docs (P, from 15:00 freeze)
> Run `make test`, `make redteam` and `make evidence` with `LLM_PROFILE=demo`, and confirm the latest anchor
> verifies on-chain. From the actual outputs only, write README (setup, deployment with Docker Compose, test
> instructions, and the testnet faucet step to fund the `ANCHOR_PRIVATE_KEY` address), `docs/technical.md`
> (architecture with the anchoring layer next to the audit log, forecast, eligibility, readiness scoring, fraud
> checks, security design, and a roadmap that includes "shared invoice registry built on the same anchoring layer,
> preventing double-financing of invoices (buyer co-signs, duplicate hashes rejected)", marked as roadmap only) and
> `docs/security-self-assessment.md` (tier implementation, red-team results, tamper-evidence via public anchoring
> as a control against repudiation and insider tampering, and the known-risk list mapped to OWASP ASI, including:
> the testnet key is stored locally; anchoring proves records are unchanged since anchoring, not that they were
> true when created; entries made between anchors are unprotected until the next batch). In the execution
> evidence, list the real testnet tx hashes with explorer links alongside the JSONL logs. Every number and tx hash
> must come from `docs/results/`.
