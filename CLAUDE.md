# CLAUDE.md: sme-copilot

FinTechathon 2026, International Track, Topic E. Hard deadline: **Tue Oct 20, 21:59 Dhaka (23:59 Beijing)**.
Code freeze 15:00 Dhaka Tuesday. Everything in English.

Remaining work is tracked in docs/dev/feature-plan.md. Read it before starting any task and update it in the same
commit when you finish.

`sme-copilot` is the codename: the repo, the backend and frontend package names and the Docker Compose project
use it. It never appears in UI text. The product name, tagline, logo and colors come from the designer and live
only in the three branding places (see Conventions).

An AI agent that runs a small business's finances day to day, acts only within limits the owner signs,
and never touches money without a signed approval. Demo business: **Maya's Corner Store** (synthetic grocery).
Second business for the Skill Pack switch: a clothing shop. All data is synthetic and labelled as such.

Judges score: task completion 40%, security & compliance 30%, innovation & interaction 30%.
Depth beats breadth. A working, logged, end-to-end flow beats three half-features.
The 0–5 on-chain challenge bonus applies to our topic (confirmed). We go for it with on-chain anchoring of audit
hashes, the first stretch goal (invariant 9).

---

## Non-negotiable invariants

Break one of these and the project loses its core claim. If a task seems to require breaking one, stop and ask.

1. **The LLM proposes; code decides.** The planner can call read/compute tools directly. Every action goes through
   `propose_action`, which the **gateway** checks against `policy.yaml` and a valid signed mandate. Nothing in
   `executor/` may be called from anywhere except `gateway/`.
2. **Untrusted content never reaches the planner as text.** Emails, PDFs, invoice photos and uploads go only to the
   quarantined extractor (no tools). The planner receives only schema-validated fields: enums, IDs, fact refs,
   validated short strings (domains, payee IDs). Never raw subjects, bodies or free-text summaries of them.
   The UI may show raw text to the owner; the planner may not see it.
3. **Values that came from untrusted content force Tier 3.** If any action argument carries `provenance="untrusted"`
   (a payee, account, amount), the gateway escalates to owner approval regardless of the tool's normal tier.
4. **Numeric Firewall.** Every number shown to the owner is a typed `Fact` computed in code with source rows.
   The LLM writes `{fact:<id>}` placeholders. Any digit `[0-9]` in LLM output outside a placeholder is rejected;
   re-prompt once, then fall back to template text. Dates are facts too.
5. **Tier 4 tools do not exist.** Large debt, hiring/firing, pricing changes, committing to deals: never add them
   to the action registry. Requests for them get analysis only, and the attempt is logged as a violation.
6. **The owner's private key never touches the server.** It lives in the browser (tweetnacl). The server stores
   only public keys and verifies Ed25519 signatures over `{action, args_hash, nonce, expiry}`. Reject replayed
   nonces and expired mandates.
7. **Everything is logged.** Every tool call, fact computation, LLM call (provider + model), gateway decision and
   execution appends to the hash-chained JSONL audit log. Never write to the log except through `audit.append()`.
8. **Never invent results.** Test numbers in docs, deck and README come from actual test runs. "12/12 blocked" is a
   target until the suite says so. Testnet tx hashes in the evidence come from a real live run.
9. **On-chain anchoring publishes hashes only.** `anchoring/` puts a Merkle root of hashes (audit-log head, newly
   signed mandates, exported Passports) into a 0-value self-transaction on an EVM testnet. Never business data,
   names, amounts or PII. Testnet only: config refuses any chain ID outside the allow-list (Sepolia 11155111,
   Base Sepolia 84532). Anchoring never blocks core flows: on RPC failure, queue the batch, retry with backoff and
   log the failure. It never moves value and is not an owner money action.

---

## Stack

- **Backend:** Python 3.12, FastAPI, Pydantic v2, SQLite (one file per business under `data/tenants/`),
  pandas/numpy. Hand-rolled agent loop. No LangChain, LangGraph, CrewAI or vector DBs.
- **LLM:** OpenAI primary (`gpt-5.6-terra` planner in dev, `gpt-5.6-sol` planner in demo profile,
  `gpt-5.6-terra` extractor). Fallback: Gemini Flash via its OpenAI-compatible endpoint. All calls go through
  `llm/adapter.py`. Never import `openai` anywhere else.
- **Frontend:** Next.js 16 (App Router, TypeScript), Tailwind, shadcn/ui, Recharts. Screens come from Claude Design;
  see `docs/design-brief.md`. The browser calls FastAPI directly at `NEXT_PUBLIC_API_URL` (no Next rewrites).
  All colors are semantic CSS variables from `styles/theme.css`, mapped into Tailwind and shadcn/ui there; charts
  use the `--chart-*` variables too.
- **Signing:** tweetnacl (browser), PyNaCl (server).
- **Anchoring:** web3.py against an EVM testnet (Sepolia by default, Base Sepolia via config). The anchor key is a
  throwaway testnet key funded from a faucet, kept in `.env`.
- **Tests:** pytest. GitHub Actions runs everything in replay mode with no API keys.

## Budget rules (we have ~$10 of OpenAI credit)

- `LLM_BUDGET_USD` (default 7) is a hard local cap. The adapter prices every call from `llm/pricing.py` using the
  returned token usage and switches to Gemini once the cap is hit. Keep ~$3 for the final recording.
- Fallback to Gemini also on `insufficient_quota`, 429, 5xx and timeouts. Back off and retry on Gemini 429s.
- `LLM_REPLAY=record|replay|off`. Tests always use `replay`. Never run the full red-team suite live more than
  once per provider without asking. The same record/replay cache also mocks the anchoring RPC, so CI never
  touches the network.
- Default to `LLM_PROFILE=dev`. Only switch to `demo` (Sol) for recording and final evidence logs.

## Layout

```
backend/app/
  main.py              FastAPI app, CORS (ALLOWED_ORIGINS), passcode auth (DEMO_PASSCODE)
  api/                 routes; thin, no business logic
  ledger/              schema, ingestion (CSV statements, receipts via extractor), PII tokenization
  engine/              P&L, margins, buffer days, forecast, financing match + safe sizing, passport, leaks
  packs/               skill.md compiler + loader, schema, detector registry and functions (skills/ holds the files)
  firewall/            Fact model, fact store, placeholder renderer, digit check
  agent/               planner loop, tool registry (read tools + propose_action), conversation state
  gateway/             policy.yaml, policy engine, mandate verification, nonce store
  executor/            sandbox_bank.py, sandbox_mailbox.py, reminder sender  (gateway-only imports)
  quarantine/          extractor + Pydantic output schemas, instruction-like-text flagging
  sentinel/            payee-change, lookalike domain, urgency, amount anomaly checks
  audit/               hash chain append/verify/export
  anchoring/           Merkle batches, testnet anchor tx, per-leaf proofs, on-chain verify, retry queue
  clock.py             simulated clock (fast-forward for demo); never use datetime.now() elsewhere
  llm/                 adapter.py, cache.py, pricing.py, prompts/{planner,extractor,brief_writer}.md
backend/data/seed/     deterministic generator (numpy seed + Faker) for both businesses + mailbox
backend/tests/         unit/, golden/, policy/, redteam/, benign/
frontend/
  app/                 routes: Today, Ask, Cash flow, Financing, Inbox, Trust
  styles/theme.css     BRANDING 1/3: every color, radius and font as semantic CSS variables
  config/app.ts        BRANDING 2/3: APP_NAME, APP_TAGLINE
  components/brand/    BRANDING 3/3: <Logo /> and the logo asset only it renders
  lib/                 api.ts (typed client), types.ts (mirrors docs/openapi.json)
skills/                skill.md library: built-in grocery, fashion, general (signed) + community examples
docs/                  design brief, build prompts, technical doc, security self-assessment
```

## Commands

```
make setup        # venv + pip install, npm install
make seed         # regenerate both businesses and the mailbox (deterministic)
make dev          # FastAPI :8000 + Next :3000
make test         # all pytest suites in replay mode + the branding check
make redteam      # attack + benign suites; writes docs/results/redteam.json
make validate-skill FILE=...  # check a skill.md the way an upload does
make evidence     # export audit log JSONL + verify chain + anchors (tx hashes) → docs/results/
make anchor       # anchor now against the live testnet (manual only; needs ANCHOR_* in .env)
```

## Tiers (canonical; `policy.yaml` must match)

| Tier | Meaning | Tools |
|---|---|---|
| T1 | Autonomous, read/compute only | all `get_*`, `list_*`, `explain_fact`, `match_financing`, `get_passport`, `rank_products_for_ads`, `product_performance`, `ad_budget_what_if` |
| T2 | Autonomous under a signed standing mandate with hard caps | `send_invoice_reminder` (invoice ≤ cap, allow-listed customer, ≤1 per customer per 3 days), `pay_recurring_bill` (≤ cap, known payee) |
| T3 | Agent prepares, owner signs the exact payload | `submit_loan_application`, `change_payee_details` (+ out-of-band call script), `delay_supplier_payment`, `send_supplier_message`, `cancel_subscription` |
| T4 | Not implemented, by design | — |

System tool: `anchor` is registered in `policy.yaml` as T1 (system caller only, testnet-only, rate-capped). It
writes a hash to a testnet, never moves value, and is not in the planner's tool registry. It runs every
`ANCHOR_BATCH_SIZE` audit entries, at the end of each demo scenario, and from the "Anchor now" button.

`propose_action` returns one of `executed` (T2 within mandate), `pending_approval` (with approval ID), `denied`
(with the rule that fired). The planner must report exactly that status and never claim an action happened
unless the result says `executed`.

## Conventions

- Money is integer minor units (cents) everywhere in code. Format only at render time.
- Every engine function is pure: `(ledger snapshot, pack, clock) -> list[Fact]`. Facts carry `id`, `value`,
  `unit`, `display`, `source_row_ids`, `computed_by`.
- Anything that gets anchored (mandates, Passports) is hashed as canonical JSON (sorted keys, no insignificant
  whitespace, UTF-8), so a verifier can recompute the exact hash from the file.
- Pydantic models for every API payload; the frontend types in `frontend/lib/types.ts` mirror them.
- Small files, explicit names, type hints, docstrings on anything security-relevant explaining which invariant
  it protects.
- Every new action tool needs: a `policy.yaml` entry, a policy test for each boundary, and at least one red-team case.
- Region-neutral product: currency, holiday calendar and payment rails are config. No country-specific framing in
  UI or prompts.
- **Branding lives in exactly three places: the theme file, the app config and `<Logo />`. Never put it anywhere
  else.** Components use semantic variables (`--brand-primary`, `--brand-accent`, `--surface`, `--text`,
  `--success`, `--warning`, `--danger`, `--chart-*` …) and never a hex, rgb or hsl literal. Every mention of the
  product name uses `APP_NAME`/`APP_TAGLINE`; every logo is `<Logo />`. The backend never refers to branding.
  A brand change touches only those three places; the branding check in `make test` enforces it.

## Definition of done (for any feature)

Works end to end on seed data · appears in the audit log · numbers trace to source rows · tests added and passing
in replay mode · nothing above violated.

## Don't

- Don't add features outside the plan's must-build list before it's done (see `docs/build-prompts.md` order).
- Don't call real banks, real email or any network service except the two LLM providers, the configured
  testnet RPC and, once the owner connects it, the Gmail API (`connections/gmail.py` reads; only
  `executor/gmail_sender.py` sends, and only to DEMO_SEND_ALLOWLIST addresses).
- Don't put secrets in code; use `.env` (gitignored). Never log or commit API keys, `ANCHOR_PRIVATE_KEY` or the
  owner key.
- Don't build wallet features, token transfers or anything that moves value on-chain. Crypto wallets stay out of
  scope; anchoring hashes is tamper-evidence, not a wallet feature.
- Don't "fix" a failing red-team test by weakening the check or the test. Report it.
- Don't hardcode a color, the product name or a logo in any component, page or chart, and don't use the codename
  in UI text. Don't weaken the branding check to get a build through.
