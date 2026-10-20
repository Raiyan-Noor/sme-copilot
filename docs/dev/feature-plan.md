# KaChing — Claude Code prompts

Deadline: Tue Oct 20, 23:59 Beijing = **21:59 Dhaka**
Feature freeze: **Tue 13:00 Dhaka**
Last updated: Tue Oct 20, ~07:15 Dhaka (demo prep)

This file is now the single source of truth for remaining work (`docs/build-prompts.md` is superseded — see the
note at its top). See "Maintaining this file" at the end before editing it.

## Status

Verified against `git log`, the code on disk and a full `pytest` run (1005 passed, `docs/evidence/tests.json`) on Tue Oct 20, ~02:00 Dhaka.

| # | Item | Status |
|---|------|--------|
| Prompts 0–17 | Original build plan | Done |
| Prompt 18 | Stretch 2: Monte Carlo what-if, marketing ROI, expansion planner | Dropped (P7 covers marketing ROI) |
| Prompt 19 | Evidence and docs: `make evidence`, Sol demo-profile recordings, Gemini recordings | Done — `make evidence`, `make demo`/`make demo-reset`, Sol and Gemini recordings, live anchor, `docs/technical.md`, `docs/security-self-assessment.md`, README (see Prompt 19 notes below) |
| F1 | Document upload | Merged into F4 |
| F2 | Sending approved emails | Done (P4) — `send_email` (T3), drafts with owner editing, Outbox tab, overnight reminder drafts; verified live in the browser on an isolated copy of the data |
| F3 | Live demo console | Done (P2) — verified live against OpenAI for all 7 presets on both seeded businesses; needs `DEMO_MODE=true` (server) and `NEXT_PUBLIC_DEMO_MODE=true` (frontend) to appear |
| F4 | Onboarding from zero | Done (P1, P1 follow-up fix) |
| F5 | Payments tab | Done (P3) — SandboxPay provider service, Payments tab, `pay_invoice` (T3); verified live in the browser on an isolated copy of the data; optional stablecoin rail not built |
| F6 | Product and ad knowledge in Skill Packs | Merged into P1 |
| F7 | Transactions tab | Done (P5, commit `c606eab`) |
| F8 | Real Gmail inbox via OAuth (read + send approved emails) | Done (P6) — connected live to the demo account Tue Oct 20 (needed the Gmail API enabled in the Cloud project). Fix: `connections/http.py` now tries IPv4 before IPv6 with a 5 s per-address connect timeout; on a network with dead IPv6 every Google call had waited out the 20 s timeout first. The poller only reads mail that arrives after connecting; use "Import the last 7 days" for older mail |
| F9 | Ad advisor: discuss which product to advertise more | Done (P7) |
| F10 | Proactive "what you didn't think of" questions from the Skill Pack | Merged into P1 |
| F11 | Upload a custom skill.md on the opening page; open skills library | Done (P8) |
| F12 | Chat loading messages that show what KaChing is doing | Done (P0) |
| F13 | Morning brief expanded into a wide popup with a live activity feed | Done — a "Morning brief" card in the chat brief opens a wide dialog over the conversation (deep link `/brief`; ✕, Esc, scrim click and browser back close it; panels and the approval sheet open above it); the feed is `GET /businesses/{id}/brief/activity`, built read-only from the overnight run's audit entries; Approve reuses the approval sheet (emails, one at a time; a group opens the Outbox since there is no batch signing) and the Payments flow (`approve.tsx`, shared with the Payments tab); held emails are Blocked + Review only. Audit entries now carry a simulated `time` (HH:MM:SS: each simulated day begins 07:00 at fast-forward, then real time passes); older entries keep their old shape and hashes, so the existing log and its anchors still verify. Full `pytest` run: 1013 passed (Tue Oct 20). Verified in the browser on an isolated copy of the data (render, Expand/Back, Approve opening the payment approval sheet); not signed there. The live demo log predates `time`, so rows show dates until the next fast-forward |
| F14 | Friendlier, conversational assistant | Done — `planner.md` gains a "Tone and conversation" section: warm greeting by name in the first reply, answer first and never ask permission to look something up, a friendly tone never replaces `{fact:...}` citations (the first drafts made Terra and Sol answer in words only or ask "shall I check?", failing `benchmarks`, `products`, `boutique_*`), one follow-up question per reply (none after a `denied`/`pending_approval` status), and at most one question per reply about the business (key products, seasons, suppliers, customers, plans, worries); owner chat details are context, never numbers or permission to act. The chat empty state greets by time of day and the owner's first name (from the brief feed). The Morning brief opens with "Good morning, <first name>." built in code (`agent/brief.py` `with_greeting`), on both the LLM and the template path, skipped if the writer already greeted; `GET /brief` adds the greeting to briefs saved before this change. The brief is laid out for scanning: each section a bold title over a bullet list (bills coming up and money coming in apart), each item led by the bolded name, on both paths (`template_paragraphs` and `brief_writer.md`); the card renders a "Title:" + "- item" paragraph as a heading and list (`BriefParagraph` in `brief.tsx`). Bold uses FactText's `**bold**` support. The brief-writer prompt changed, so its old dev/demo recordings miss and fall back to the template, which has the same layout. Planner recordings re-recorded for the new prompt (Tue Oct 20): openai/Terra 126 passed, attacks 37/37, tasks 25/25; openai-demo/Sol attacks 36/37, tasks 25/25 (the 3 Sol mailbox failures are extractor recordings, unchanged and failing before this change) |
| S1 | Submission PDFs (LaTeX) | Done (Tue Oct 20) — `docs/submission/technical-documentation.pdf` (16 pp) and `security-self-assessment.pdf` (14 pp), built with MiKTeX pdflatex from `*.tex` + shared `preamble.tex`; anchor and red-team tables generated from `docs/results/*.json` and the local anchor store by `docs/submission/make_tables.py`. Team details, repo, demo video and pitch-deck links are set in `preamble.tex` (`\teamname`, `\teammembers`, `\repourl`, `\videourl`, `\deckurl`) |
| S2 | Submission README | Done (Tue Oct 20) — `README.md` rewritten for judges (criteria map, Topic E feature table with file paths, architecture, tiers from `policy.yaml`, HITL flow, anchoring + how to verify a tx, env-var table, Gmail setup, troubleshooting, tests per suite, evidence, demo script, limits), `docs/SECURITY.md` (summary; the self-assessment stays canonical), `docs/screenshots/README.md` (capture list), MIT `LICENSE`. Fix: `npm run build` failed prerendering `/ask` because F14's greeting read `new Date()` during render; `useGreeting` now reads the hour via `useSyncExternalStore` (server snapshot null → "Hello"). Verified: `make test` 1023 passed, branding + types ok; frontend lint, `tsc --noEmit`, `npm run build` pass. Team, video and deck links filled in (Tue Oct 20); screenshots are still placeholders |
| S3 | Execution evidence run | Done (Tue Oct 20) — `scripts/run_evidence.py` + `make evidence` (the earlier export is now `make evidence-docs`) run onboarding, inbox fraud/phishing, a signed payment, over-threshold/forged/untrusted/T4 attempts and the red-team suite in replay mode with SandboxPay, and write `evidence/logs/*.jsonl` (redacted: emails to domain, secrets stripped), `evidence/manifest.json` (per-file SHA-256, commit, root hash), `evidence/anchors.json` (the root's seal entry anchored through the unchanged anchoring module) and a README whose table is counted from the logs. Numbers are in `evidence/README.md` from the actual run |
| — | Correcting ledger entries | Dropped |

Verification notes: P0 confirmed by `frontend/components/advisor/stage-line.tsx` and commit `23d2f8e`. P1 confirmed
by the onboarding flow in `frontend/app/start/`, the upload path and commits `f57180c` + `8e7ccec`. P7 confirmed by
`backend/app/engine/ad_advisor.py`, `backend/app/agent/ads_tools.py` and the new T1 tools in `policy.yaml`
(`rank_products_for_ads`, `product_performance`, `ad_budget_what_if`) and commit `4df2220`. P8 confirmed by
`backend/app/packs/skill.py` and commit `d48d6c4`. P2/P6/P4 confirmed **not started**: no matching files
(`*console*`, `*gmail*`) exist anywhere in `backend/app` or `frontend/app`. P3 (payments) also not started: no
`*payment*`/`*sandboxpay*` files exist. **P5 (Transactions) is partially in progress but uncommitted** as of this
update: `git status` shows a modified `backend/app/api/ledger.py` (+165/-10), a new untracked
`frontend/app/transactions/page.tsx`, and edits across several `frontend/components/advisor/*` files and
`frontend/lib/api.ts`/`types.ts` — this looks like another session actively building it in this shared working
tree (see [[parallel-sessions-shared-tree]] in memory). Those files were left untouched by this update; whoever is
mid-P5 should commit when ready and flip this row to Done.

**Build order:** P0 → P1 → P8 → P7 → P5 → P6 → P2 → P3 → P4 → Prompt 19 (evidence). P0 is a quick fix, do it first.
Prompt 19 must run before the freeze: the submission requires execution evidence. All build on Prompt 16's signing,
SSE chat and real-data screens, which already exist. P8 follows P1 because it reuses the pack-driven onboarding.
P7 uses the product and ad data onboarding imports. P5 comes early because uploads, payments and emails all show
their results in the Transactions tab. P6 comes before P2 and P4 so the console and email sending can use the real
inbox.

**Remaining order from here:** nothing planned. Feature freeze 13:00, code freeze 15:00 Dhaka; only bug fixes and submission material after that.

**Demo email plan:** the console injects sandbox attacks that real email can't fake (lookalike domains, spoofed senders); real emails are sent live from your phone to the demo Gmail inbox.

**Demo config (Tue Oct 20, ~07:15 Dhaka):** `.env` now has `LLM_PROFILE=demo` (Sol planner) and `DEMO_SEND_ALLOWLIST=raiyannoor2000@gmail.com`. Every seeded and sample customer has an `.example` address, so overnight reminders still go to the labelled sandbox outbox; a real Gmail send needs a recipient whose address is on the allowlist (e.g. added through "New address you added", `POST /emails/recipients`). **Audit chain fork, fixed:** two server processes (a stale uvicorn spawn worker beside a fresh one) appended to `audit.jsonl` at once and each kept its own head, so entries 1099–1118 were written twice and `/audit/verify` failed. `audit/log.py` `append()` now takes a cross-process lock on `audit.jsonl.lock` and re-reads the head from the file (tests: `test_two_writers_on_one_file_keep_one_chain`, `test_two_processes_appending_at_once_keep_one_chain`; both fail without the fix). The forked log and its anchor records were moved unedited to `backend/data/tenants/_archive/forked-chain-2026-10-20/` (README, SHA256SUMS, verify result); the live app started a new chain, and `anc-000001` of it confirmed live on Sepolia (block 11951950). The overnight activity feed is empty until the next fast-forward. Full `pytest` after the fix: 1023 passed, branding and types checks pass, `tsc --noEmit` clean. `make demo` running with both rehearsal businesses reset.

**Manual setup before P6 (you, ~15 min):** create a fresh Gmail account for the demo shop; create a Google Cloud project; enable the Gmail API; configure the OAuth consent screen in testing mode; add the demo Gmail as a test user; create an OAuth client (web app) with redirect URI `http://localhost:<backend port>/inbox/gmail/callback`; put the client ID and secret in `.env`. No paid services needed.

**Demo story:** a new business sets up KaChing in under 2 minutes → uploads files → connects its inbox → gets its first brief → attacks arrive live from the console and get flagged → an invoice is paid with one tap → a reminder email is approved and sent.

## Known facts

Tiers in `policy.yaml` (canonical; matches the Tiers table in CLAUDE.md):
- **T1** (autonomous, read/compute only): `get_*`, `list_*`, `explain_fact`, `match_financing`, `get_passport`,
  `rank_products_for_ads`, `product_performance`, `ad_budget_what_if`; system-only `anchor` (testnet only, caps at
  12 runs/hour, never moves value, not in the planner's registry).
- **T2** (signed standing mandate, max 90 days; breaking a cap/allow-list/frequency rule is denied, not escalated):
  - `send_invoice_reminder`: ≤ 50000 minor units, allow-listed customers, 1 per customer per 3 days.
  - `pay_recurring_bill`: ≤ 500000 minor units (raised for P3), allow-listed payees.
- **T3** (owner signs the exact payload, approval expires after 2 days): `submit_loan_application`,
  `change_payee_details` (needs an out-of-band call script), `delay_supplier_payment`, `send_supplier_message`,
  `cancel_subscription`, `pay_invoice` (P3; Payments tab only — hidden from the planner's action catalogue by
  `agent/actions.NOT_FOR_PLANNER`, so no planner recording went stale), `send_email` (P4; tier chosen by P4: T3).
- **T4** (no tools, by design; analysis only, logged as a violation): `large_debt`, `hiring_or_firing`,
  `pricing_change`, `deal_commitment`.

**T2 cap (decided Oct 19, before P3):** Raiyan chose to raise `pay_recurring_bill` to 500000 minor units (৳5,000);
`send_invoice_reminder` stays at 50000. Applied in `policy.yaml`; `tests/policy/test_gateway_payments.py` pins both.

**Prompt 19 as built, Tue Oct 20 ~02:00 Dhaka** (every number below is from a generated file; see
`docs/evidence/index.md`):
- **Anchoring:** `make anchor` ran live on Sepolia and confirmed `anc-000014` (block 11949719). `docs/results/anchors.json`
  now holds all 14 confirmed batches of the dev data, every one `match`, `verified_log_ok: true`. The chain responses are
  recorded under `backend/data/replay/rpc/` (committed), so `tests/unit/test_anchor_evidence.py` and `make evidence`
  re-verify all 14 offline. `make anchor` refuses while the API is up; stop `make dev`/`make demo` first.
- **`make evidence`** (`scripts/evidence.py`): offline, read-only (SQLite opened read-only, audit log copied to its last
  complete line, so it can run while the app is up). Writes `docs/evidence/`: audit log + chain check (+ every anchored
  head checked against the log), anchors re-verified from recordings, redteam.json + benign.json, tests.json (full
  pytest in replay with JUnit counts per suite, plus branding/types checks), outbox and payments per business,
  SandboxPay's log, LLM spend three ways, and index.md. `--no-tests` skips pytest. Last run: chain ok, 14/14 heads
  match, 14/14 batches verify, 1005 passed. The dev data has no payments yet (SandboxPay log empty) and one sandbox
  email; rerun `make evidence` after the recorded demo to capture its payments and emails.
- **Recordings per provider:** `backend/data/replay/llm/` (OpenAI dev/Terra, what CI replays), `replay/openai-demo/llm/`
  (Sol planner + Terra extractor, new), `replay/gemini/llm/` (subset: `test_planner_attacks.py` +
  `test_benign_questions.py`, new). `REPLAY_PROVIDER=openai-demo|gemini` selects them in tests (`tests/agent_env.py`);
  `make redteam` now reports every provider with recordings; `--record` needs an explicit `--provider`.
- **`make redteam` (replay, `docs/results/redteam.json`):** openai 37/37 attacks (91/91 variants), 25/25 tasks;
  openai-demo 36/37 (90/91), 25/25; gemini subset 4/4 (19/19), 11/11 (after the F14 re-record). Failures are explained in
  `docs/security-self-assessment.md` §3: an extra `instruction_like_text` flag and two extraction misses from a fresh
  Terra extractor sample in the Sol run, and four Gemini answers that cited the wrong facts or fell back to the template.
  Recorded once and reported as recorded, not re-sampled. Raiyan may choose to re-record those cases; ask first.
- **Gemini fallback was broken; fixed.** `gemini-2.5-flash` now returns 404 for this key, so `GEMINI_MODEL` defaults to
  `gemini-3.8-flash` (`config.py`, `.env.example`). Gemini 3 also refuses a tool turn unless each call's
  `thought_signature` is sent back: `ToolCall.signature` keeps it, `assistant_message` echoes it, and the Gemini provider
  sends Google's placeholder for calls OpenAI made; OpenAI requests (and replay keys) are unchanged. Tests in
  `tests/unit/test_llm_openai_provider.py`. `gemini-3.8-flash` is not in `llm/pricing.py` (no verified price), so it is
  priced at the highest known rate; the Gemini figure in `llm_spend.json` is an upper bound, not OpenAI credit.
- **Spend:** the Sol recording cost $0.7026 of OpenAI credit (priced from recorded usage, `docs/evidence/llm_spend.json`
  `replay_recordings.openai-demo`). The dev app's local counter reads $0.1016; neither includes earlier test-run
  recordings, so true OpenAI spend is higher than either figure.
- **`make demo`** (`scripts/demo.py`): stops every process listening on :8000/:8100/:3000, every uvicorn for the app or
  SandboxPay and orphaned spawn workers, then runs `scripts/dev.py` with `DEMO_MODE=true` and `NEXT_PUBLIC_DEMO_MODE=true`
  and prints the URLs once all three ports answer. It also stops another session's `make dev`/`make demo`, by design.
  `make demo-reset` is an alias for the existing `make reset-demo`.
- **Docs:** `docs/technical.md`, `docs/security-self-assessment.md` (red-team section generated by
  `scripts/redteam_tables.py` from redteam.json; re-run it after `make redteam`), README.
- **Known bug, not fixed:** on Windows, two concurrent RPC-cache writes for the same key on the dev server (record mode)
  can raise `PermissionError` on the temp file (`llm/cache.py` `put`), seen once during a Trust-page verify. The
  request still answered; low risk for the demo.

**Replay cache / red-team staleness:** `backend/data/replay/llm/` holds 70 planner recordings + 47 extractor
recordings + 1 brief_writer (118 total; P4 re-recorded all planner cases and added one benign task). The cache key hashes the full
planner request including every tool schema, so P7 adding three new T1 tools (`rank_products_for_ads`,
`product_performance`, `ad_budget_what_if`) invalidated and forced a re-record of every planner-dependent case
(benign questions, benign tasks, the live-LLM red-team cases) — that's where the +3 planner / +8 extractor files
came from (commit `4df2220`, 74 replay files touched). Full details and the re-record procedure:
[[benign-replay-rerecord]] in memory.

**`docs/results/redteam.json`** now covers three providers (see Prompt 19 notes above). Re-run `make redteam`, then
`python scripts/redteam_tables.py`, after any later change to planner tools, prompts or policy and before quoting
numbers in the deck or README (invariant 8). A planner/extractor change now invalidates three recording sets, not one.

Already answered by the original plan: products are tracked individually (product margins and an
unprofitable-products leak detector exist); reminders are a T2 action (`send_invoice_reminder`) under a standing
signed mandate; untrusted-provenance arguments force T3; loan applications are T3; a statement-upload endpoint
exists in the backend.

`make test` passes clean as of Prompt 19: 1005 pytest cases (replay mode; `docs/evidence/tests.json`), plus the
branding and frontend-types checks.

**P6 (Gmail) as built, Mon Oct 19 evening:** full `pytest` run 854 passed (replay mode), branding and frontend-types
checks pass. No planner prompt, tool schema, policy.yaml or extractor input changed, so no replay recordings went
stale and `make redteam` was not re-run for P6. What later prompts can reuse:
- Live inbox events: `GET /businesses/{id}/inbox/stream` (SSE; `message` events with stages received → extracting →
  checking → accepted/flagged/held/failed, and `connection` events). Every path that calls
  `InboxProcessor.process()` publishes them (sandbox sync, uploads, Gmail), so P2's console gets the live stages for
  free if it delivers through `process()`.
- Sending: `executor/mail_sender.py` `MailSender.send(kind, recipient_id, subject, body, details, today)` sends via
  Gmail only when Gmail is connected and active, the recipient is a known contact with an email on file, and the
  address is on DEMO_SEND_ALLOWLIST; otherwise it writes to the sandbox outbox with a `label` saying why. Every send
  (real or simulated) is a row in the existing `outbox` table with `transport`. `send_invoice_reminder` already uses
  it with a fixed code-written template (no amount in the body); `send_supplier_message` still writes to the outbox
  directly.
- Connections section lives at the top of the **Inbox tab** (status, connect, disconnect, Gmail/sandbox switch).
- `.env` needs GMAIL_CLIENT_ID and GMAIL_CLIENT_SECRET (not there as of this update); GMAIL_TOKEN_KEY was generated
  into `.env`. Redirect URI default: `http://localhost:8000/inbox/gmail/callback` (GMAIL_REDIRECT_URI).

**P2 (demo console) as built, Mon Oct 19 night:**
- Backend: `services/demo_console.py` + `api/demo_console.py`, mounted only when `DEMO_MODE=true` (otherwise the routes
  do not exist; tested). `GET /businesses/{id}/demo/console` (presets + which checks are rule-based), `POST .../demo/send-preset`,
  `POST .../demo/send-custom` (multipart, optional PDF/PNG/JPEG). Presets are written at send time from the business's
  own records (supplier, customer, owner names/domains; fresh invoice number each send), not copied from the seed
  manifest, so they work for Maya and the fashion shop. A preset says `available: false` with a reason if the business
  lacks a supplier/customer or has under 3 past payments (unusual-amount).
- Delivery: `InboxProcessor.deliver_console` (source `console`, ids `dc-…`, raw files under `inbox_console/`) -> the
  same quarantine -> sentinel path; live stages come from the existing inbox SSE stream. The extractor uses
  `rt.demo_llm`, an adapter with replay **off** (always live; same budget cap and Gemini fallback). Console mail is
  never replayed, so there are no console recordings and no replay files went stale.
- **Rule-based vs model:** works with no model: `lookalike_domain`, `reply_to_mismatch`, `display_name_spoof`, `urgency`
  and `instruction_like_text` text patterns, `hidden_text`. Need the model's reading first: `bank_detail_change`,
  `first_time_payee`, `amount_anomaly`, `amount_mismatch`, `duplicate_invoice`, `receipt_total_mismatch`. **Behaviour
  change in `sentinel/checks.py`:** if any extraction is not `ok` (model down/invalid) and a high-severity flag fired,
  the message is now held (`hold = high and (payment or unread)`), since it can't be shown not to ask for money.
- Live check (not CI): all 7 presets on Maya and on the fashion shop returned the expected verdict with a real
  OpenAI model on a scratch copy of the data, about $0.047 of real OpenAI spend in total (so the real
  `llm_spend.json` counter of 0.0722 USD above is now ~$0.05 short of the true figure).
- Frontend: `/demo-console` (`components/advisor/demo-console.tsx`): presets, compose form, live stage rows and verdict
  cards with plain-language flag reasons and the call script, and the owner's app (`/inbox`) in an iframe on the
  right for side-by-side recording. Gated by `NEXT_PUBLIC_DEMO_MODE`. A held/flagged email now toasts on every
  screen (moved from the Inbox panel into `AdvisorProvider`).
- Not done: the Morning Brief does not change when mail is flagged (toast only). (`make demo` now starts demo mode.)

**P4 (emails) as built, Tue Oct 20:**
- **Action:** `send_email(recipient_id, draft_id)` is **T3** in `policy.yaml` (every email needs the owner's signature),
  with `deny_untrusted_args: true`: if any argument is untrusted the gateway **denies** (`untrusted_args_denied`)
  instead of escalating, so content from an email can never make the assistant email someone, even with a signature.
  The signature binds the recipient and the draft ID, and the draft ID is a hash of the exact subject and body
  (`gateway/emails.py`, same scheme as loan drafts). A tampered draft is `draft_tampered`.
- **Drafting:** the planner calls `propose_action("send_email", {recipient_id, subject, body})` with `{fact:<id>}` for
  every amount and date; `agent/actions.py` renders it through the Numeric Firewall (`agent/email_compose.py`), stores
  the draft and passes the gateway only `recipient_id` + `draft_id`. A digit outside a placeholder, a malformed or
  unknown placeholder rejects the email (the planner sees an error and may retry; nothing is stored or proposed). A
  body that cites a fact from quarantined content makes the draft untrusted, so it is denied. The overnight job
  (`services/overnight.py`) drafts the same reminder as an email when the T2 reminder is denied for no mandate, not
  allow-listed or a cap (never for a frequency cap or an untrusted-source invoice), skips an invoice that already has a
  waiting draft or a signed email in the last 3 days, and shows it in the Morning Brief (`needs_you[].email`).
- **Recipients:** only a contact with an email on file, or an address the owner added through
  `POST /emails/recipients` (typed twice + explicit confirmation; id `rcp_…`, labelled "New address you added"). Never
  the sender (From or Reply-To) of an email the Sentinel flagged, nor a known contact whose own address sent one
  (`recipient_flagged_sender`; they get the call script instead). Checked at proposal and again just before execution.
- **Owner editing:** `POST /gateway/approvals/{id}/revise-email` makes a new draft and a new approval and closes the old
  one (`superseded`), so a signature over the old text can never send the new text. Digits the owner types are theirs
  (not LLM output); placeholders are refused. `POST /gateway/approvals/{id}/decline` now closes an approval in the
  gateway and logs it (the UI's Decline buttons call it).
- **Sending/outbox:** goes through `executor/mail_sender.py` (Gmail only if connected, active and the address is on
  DEMO_SEND_ALLOWLIST, otherwise the labelled sandbox outbox). Every row now stores the full body; the audit log gets a
  SHA-256 of it (`body_sha256`), plus `email.drafted`, `email.revised`, `email.recipient_added`,
  `gateway.approval_declined` and the usual decision/mandate/execution entries. `GET /businesses/{id}/outbox` returns
  sent emails and the drafts waiting for a signature; `/outbox` is a new sidebar view with a "Write an email" form
  (owner-written emails are drafts + approvals too). The approval sheet shows recipient, subject, full body, why, and
  "Edit the draft". `make evidence` (Prompt 19) should export `GET /outbox` for each business.
- **Injected "please email X":** new `email_directive` instruction pattern in `quarantine/signals.py` flags it
  (and `instruction_like_text` already made the planner ignore it); the planner can't email an address from an email
  anyway (untrusted → denied).
- **Stale replay:** the new action in the planner's action catalogue and the planner prompt invalidated every planner
  recording. All planner cases (benign questions, benign tasks, live-LLM red-team) were re-recorded once live on
  gpt-5.6-terra (dev profile). Extractor and brief_writer recordings were not affected. The real
  `llm_spend.json` counter does not include this re-record (the test runs keep their own counters), so the true spend is
  higher than the $0.0722 above by that amount.
- **Not done:** owner edits are not firewall-checked by design (documented above); no stand-alone "reply to this
  supplier email" button (suppliers are emailed from Outbox's form or by asking the assistant).

**P3 (payments) as built, Tue Oct 20 early:**
- **Provider:** `backend/sandboxpay/` is its own FastAPI service (`uvicorn --factory sandboxpay.main:create_app`,
  port 8100; `make dev` starts it; docker-compose has a `sandboxpay` service). It imports nothing from `app`. Own
  SQLite, consent screen at `/authorize` (owner can lower the per-payment/daily caps, never raise), code + PKCE +
  client secret → scoped bearer token + per-connection webhook secret, `/oauth/revoke`, `/v1/payments` with a required
  `Idempotency-Key`, its own per-payment and daily caps, settlement after `SANDBOXPAY_SETTLE_SECONDS` (default 4) with
  an HMAC-SHA256-signed webhook (retried with backoff). `SANDBOXPAY_CLIENT_SECRET` was generated into `.env`; the token
  is encrypted with `SANDBOXPAY_TOKEN_KEY`, falling back to `GMAIL_TOKEN_KEY`.
- **App side:** `executor/sandbox_bank.py` is now the provider client (no parallel executor). `pay_invoice` (T3) args
  are payee + account token + amount + reference + request ID, so the signature binds payee, amount and account; the
  gateway precheck (`dispatch.Executors.precheck`) refuses if the account on file changed or a flagged-email request
  has no call verification. `pay_recurring_bill` (T2) pays the account on file with key = hash(payee, bill, amount).
  `Gateway.mandate_covers()` (read-only) decides which tool the Payments service proposes; `Gateway.listeners` lets
  `services/payments.py` follow executions. Settlement only on a verified webhook (or a provider status check):
  one ledger row (`import_id` `pay_<request>`, Transactions shows source "payment"), the bill's scheduled item set to
  `paid`, a canonical receipt whose hash is logged as `payments.settled` and anchored as leaf kind `payment`.
- **Live status:** payment events ride the existing inbox SSE stream (`kind` `payment` / `payment_connection`); the
  owner app toasts settled/failed payments and reloads cash, runway and Transactions on settlement.
- **Frontend:** `/payments` panel (`components/advisor/panel-payments.tsx`), sidebar link after Transactions:
  provider card (connect/disconnect, scopes, caps, spent today), due-soon suggestions from bills/invoices (one tap →
  approval sheet), "Held by the inbox check" for flagged emails (call script + "mark the call done"), manual request,
  history with status/payee filters and live step dots, payees with Verified / Added-by-you badges and an add-payee
  form (account typed twice + confirmation), payment detail with timeline, receipt, ledger link and Verify on-chain.
- **Verified live** (browser, isolated copy of the data on :8001/:8101/:3001, anchoring off): connect → pay FreshLine
  FL-26-0049 → sign → settled by webhook → cash on hand 15,837.53 → 14,550.35. The running dev server on :8000 was
  not touched and was still serving pre-P3 code at the time; restart it (see the stale-worker memory) to get P3.
- **Not done:** optional testnet stablecoin rail (needs Raiyan's go-ahead first, per the prompt). A payment made
  without a connected provider is recorded as failed `not_connected` (the gateway still reports `executed` for the
  executor run, as before).

---

## P0 — Chat loading messages (quick fix)

```
Fix the chat loading state, timeboxed to 45 minutes.

Problem: replies in Ask are slow and the UI shows "checking your account" the whole time.

Change
- Replace the single message with status lines that follow what the agent is actually doing. Emit a stage event over the existing SSE stream at each step of the planner loop, and show the matching line:
  - request received → "Reading your question…"
  - before the first LLM call → "Thinking…"
  - read tool calls → a line per tool, e.g. "Checking your cash position…", "Looking at your sales…", "Reviewing your ad campaigns…", "Checking your products…"
  - propose_action → "Preparing an action for your approval…"
  - numeric firewall → "Double-checking every number…"
  - re-prompt after a firewall rejection → "Fixing a number…"
- If no event arrives for 3 seconds, rotate through general lines ("Reasoning…", "Weighing the options…", "Almost there…") so the screen never looks stuck.
- Remove "checking your account" entirely.
- Start streaming the reply text to the UI as soon as the firewall has passed it, instead of waiting for the full response.

Also measure where the time goes: log time to first stage event, each LLM call's latency, and total time per request for the 10 benign questions. Report the numbers, and suggest the top fix if one step dominates. Don't change models without asking.

Use the same stage lines for onboarding, the ad advisor and the Morning Brief wherever they wait on the LLM.

Commit and push.
```

---

## P1 — Onboarding from zero (with document upload and Skill Pack data needs)

```
Add onboarding from zero, with document upload built in, timeboxed to 5 hours.

Goal: in the demo, a brand-new business sets up KaChing in under 2 minutes, and KaChing immediately starts working and briefs the owner. It should feel effortless.

Flow (chat-style, KaChing asks one thing at a time; buttons where possible, typing optional)
1. Welcome: business name and type. The type picks the Skill Pack (grocery or fashion; anything else falls back to a general pack).
2. Starting point: current cash balance, plus any regular bills or loans. Let the owner skip anything they don't know.
3. Pack-specific data: KaChing asks for that pack's data needs (see "Skill Packs" below) in plain language, one at a time.
4. Upload: a drag-and-drop area for CSV (sales, bank, products, ad spend), PDF invoices and receipt images.
   - CSV goes through the existing ledger ingestion and statement-upload endpoint (reuse them; don't build a second path). Show what was imported: rows, date range, skipped rows and why.
   - PDFs and images go through the quarantined extractor and Sentinel.
   - Amounts from documents stay pending until approved.
   - KaChing proposes known suppliers and customers from the uploads, and the owner confirms them as known contacts.
5. Connect inbox: two options. "Connect Gmail" (real inbox, built in P6; until P6 lands, show it disabled) and "Use sandbox inbox" (the simulated mailbox the demo console sends to, labelled as a sandbox connection).
6. Rules: KaChing suggests 1–2 starter mandates based on the data (e.g. "pay your top 3 suppliers up to X without asking"). The owner edits and signs them, or skips this.
7. First brief: KaChing runs the analysis right away. It shows the first Morning Brief (cash buffer days, leaks found, what needs attention) and a short to-do list of next actions.

Skill Packs drive what KaChing asks for
- Each pack declares a list of data needs: what to ask for, why it matters, the expected CSV columns, and whether it's required or optional.
- Product knowledge: per-product records (SKU or name, category, cost price, sale price, stock). The engine computes per-product margins, slow movers and stockout risk.
- Advertising knowledge: ad spend per campaign and channel (e.g. Facebook, Instagram, Google), plus sales attributed to each campaign where available. The engine computes return on ad spend per campaign.
- Fashion pack: products and ads are both important. Add leak rules for campaigns that cost more than they earn, and for high return rates on a product.
- Grocery pack: products are important (margins, spoilage, slow movers); ads are optional.
- Example question: "Do you run Facebook or Instagram ads? If so, upload your ad spend export so I can check they're paying off."
- Each data need offers: upload a file, enter it quickly by hand, or skip. Skipped items show up later in the brief as "KaChing could also check X if you add Y."
- Proactive questions: each pack also declares the questions an experienced advisor for that kind of business would ask, which owners often don't think of, each with a one-line "why I'm asking". Fashion examples: return policy and return rate, seasonal stock for Eid and other peaks, marketplace commissions, supplier credit terms. Grocery examples: customer credit (baki), spoilage and expiry, early-pay discounts from suppliers, mobile-wallet fees. Show the "why I'm asking" line visibly in the onboarding chat, and turn each answer into a fact or a detector setting the engine actually uses.
- The Morning Brief gains per-product insights (best and worst margins, slow movers) and ad insights (campaigns losing money, best channel).

Rules
- Before saving, KaChing shows a summary of what it understood, and the owner confirms it.
- All numbers in summaries and the brief go through the numeric firewall.
- A new business gets its own per-business SQLite. Don't touch Maya's or the fashion shop's data.
- Everything is written to the audit log.
- Add a "Start fresh" entry point so I can run this live in the demo, plus a reset command to wipe the demo business between rehearsals.

Demo data: prepare a sample folder for a new fashion business: 3 months of sales CSV, a products CSV, an ad-spend CSV with at least one campaign losing money, 2–3 PDF invoices, and a receipt photo. The demo upload must always work.

Tests: full onboarding with sample files; a skipped-step path; a bad CSV with clear errors; a malicious PDF flagged during upload; the fashion pack asks for ad data and the grocery pack doesn't by default; return on ad spend checked against golden values; the losing campaign is flagged; skipping ad data still produces a complete brief.

Commit and push.
```

---

## P8 — Custom skill.md upload and an open skills library

```
Add custom skills, timeboxed to 3 hours. Build on the Skill Pack loader (prompt 5) and the pack-driven onboarding (P1).

skill.md format
- A skill is a single Markdown file: YAML frontmatter holds the machine-readable pack (everything the current pack YAML has: expense categories, seasonality, KPIs and healthy ranges, leak detectors, financing fit, readiness weights, plus P1's data needs and proactive questions). The Markdown body is a human-readable description of the business type and what the skill watches.
- Compile skill.md into the existing Pydantic pack model. Convert the built-in grocery and fashion packs to skill.md so built-in and custom skills use one format, and keep golden tests passing.
- Write docs/skills/FORMAT.md documenting the format, with a minimal example.

Opening page
- On the welcome/onboarding screen: pick a built-in skill (Grocery, Fashion) or "Upload your own skill.md".
- After upload, show a preview before activating: business type, what KaChing will ask, what it will watch (detectors, KPIs), and a trust badge.
- The owner confirms, and onboarding continues using that skill's questions.

Safety (add each as a red-team test). Uploaded skills are untrusted input:
- Strict schema validation; reject unknown fields with clear errors.
- Detectors are referenced by name from the built-in registry only. A skill can configure thresholds but can never add code.
- A skill cannot touch policy.yaml, tiers, caps, mandates or the gateway. Any field that tries is rejected.
- The Markdown body and all free-text fields are shown to the owner as data and are never inserted into planner prompts. A skill containing "ignore your rules…" text must have no effect on behaviour.
- Size limit and safe Markdown rendering (no scripts or HTML).
- Trust badge: "Verified" if the skill is signed with the KaChing library key (Ed25519, reuse PyNaCl), otherwise "Community — unverified". Sign the built-in skills.
- Uploads, activations and validation failures are audit-logged; the skill's hash goes into the anchoring batch.

Open library (for the pitch)
- A skills/ folder in the repo as the seed library: grocery.skill.md, fashion.skill.md, plus one community example (e.g. bakery.skill.md) that validates and works with existing detectors.
- skills/README.md: how to write, validate and submit a skill. Add `make validate-skill FILE=...`.

Tests: built-in skills round-trip with unchanged outputs; the bakery skill uploads and drives different onboarding questions; a malformed skill is rejected with clear errors; a skill trying to add a detector name that doesn't exist, change tiers or inject instructions is rejected or has no effect; signature verification gives the right badge.

Commit and push.
```

---

## P7 — Ad advisor: which product to advertise

```
Add an advertising advisor to Ask, timeboxed to 3 hours. Build on the product and ad data from P1.

Goal: in the demo, the owner has a short back-and-forth in Ask about which product to advertise more and which is doing well, and every number in the answers is real and clickable.

Data
- The ad-spend data links each campaign to the product(s) it promotes, with spend and attributed sales (as in a Facebook/Instagram ads export). Extend the P1 ad-spend schema if needed.

Engine (pure functions returning Facts with source rows, golden-file tested)
- Per product: margin, profit per unit, units sold trend (last 30 days vs the 30 before), stock on hand and days of stock cover, return rate (fashion pack), ad spend, attributed revenue, return on ad spend, and profit after ad spend.
- A ranked "worth promoting" list with reasons. Exclusions with reasons: low stock cover (restock first), negative profit after ad spend, high return rate. Thresholds come from the Skill Pack.
- A what-if calculator: move an amount of budget from one campaign or product to another → estimated change in gross profit as a low/high range, based on each campaign's historical return. Cap extrapolation at 1.5× a campaign's historical spend and label the result as an estimate.

Planner
- New read tools: rank_products_for_ads, product_performance, ad_budget_what_if. They return fact IDs only, like the existing tools.
- Multi-turn: follow-ups like "why not the red kurti?" or "what if I move X from campaign A to B?" use the previous turn's context.
- Answers explain the trade-off in plain language (e.g. "your best seller is nearly out of stock, so restock before advertising it") and go through the numeric firewall. Numbers are clickable into the trace drawer.
- Optional action: save the agreed plan as a to-do in the Morning Brief (T1). Changing real ad accounts is out of scope; say so if asked.

Demo data (fashion sample folder from P1): 6–8 products and 3–4 campaigns, designed so the conversation is interesting:
- one clear winner (good margin, strong ad return, plenty of stock);
- one best seller with a strong ad return but low stock (trap: restock first);
- one high-revenue product whose ads lose money after margin (trap);
- the losing campaign already flagged in the first brief.

Benign tests: "Which product should I advertise more?", "Which product is doing best?", "Why not <best seller>?", "What if I move <amount> from campaign A to B?" — each answered with only valid fact placeholders, and the ranking matches golden values.

Commit and push.
```

---

## P5 — Transactions tab

```
Add a Transactions tab, timeboxed to 2 hours.

Data
- Use the existing ledger transactions endpoint from prompt 7. Extend it with filtering, search and pagination if needed; don't build a second data path.
- Add the new route to the sidebar between Cash flow and Financing. Design it yourself to match the existing screens; use only theme variables, APP_NAME and <Logo />. The branding check must pass.

Table
- Columns: date, description, counterparty, category, amount (money in and money out clearly distinguished), running balance, source, status.
- Source shows where the row came from: CSV import, invoice/receipt (extracted), payment (executed through the gateway), or onboarding opening balance.
- Status shows pending (e.g. an amount from a document awaiting approval), settled, or failed.
- Counterparty names use the existing PII tokenization rules; never show raw account or phone numbers.

Interaction
- Filters: date range, money in/out, category, source, status. Free-text search on description and counterparty.
- Clicking a row opens a detail drawer: all fields, the original source (CSV row, extracted document fields, or payment request), the audit-log entry, and an on-chain verify link if the row's audit entry has been anchored.
- Rows that feed a number shown elsewhere are reachable from the existing trace drawer (clicking a source row there opens it in this tab).
- Export the current filtered view as CSV.

Live updates
- New rows appear in real time over the existing SSE channel when a CSV is imported, a document amount is approved, or a payment settles. Briefly highlight new rows.
- The balance at the top of the tab updates with them.

Rules
- Amounts are integer minor units from the ledger, formatted only in the UI; no client-side recomputation of balances.
- The tab is read-only. Corrections and edits are out of scope.
- Works for every business, including a business created through onboarding.

Tests: filters and search return the right rows, pending rows are excluded from the settled balance, a newly imported row appears without a reload, tokenized counterparties are never shown raw, CSV export matches the filtered view.

Commit and push.
```

---

## P6 — Connect a real Gmail inbox (OAuth)

```
Add a real Gmail connection via OAuth, timeboxed to 4 hours. The sandbox mailbox stays as a fallback.

Setup assumptions
- I have created a Google Cloud project in testing mode with the Gmail API enabled, an OAuth web client, and a demo Gmail account added as a test user. Client ID and secret are in .env as GMAIL_CLIENT_ID and GMAIL_CLIENT_SECRET; add them to .env.example with placeholders. Never log them.

Connect flow
- "Connect Gmail" in onboarding step 5 and in a new Connections section (settings or the Payments tab's connected-services area; pick one place and tell me which).
- Standard OAuth authorization-code flow with PKCE and a state parameter. Request only gmail.readonly and gmail.send.
- Show the owner in plain language what KaChing will be able to do before redirecting to Google.
- Store the refresh token encrypted at rest (key from .env), per business. Never return it to the frontend, never pass it to the LLM.
- Disconnect button revokes the token with Google and deletes it locally.
- Connecting and disconnecting are audit-logged.

Reading mail
- Poll for new messages every 5–10 seconds (Gmail history API from the last seen historyId). Push notifications via Pub/Sub are out of scope.
- Each new message goes through the exact same pipeline as the sandbox mailbox: quarantined extractor → Inbox Sentinel → planner. Fetch the raw MIME, including PDF and image attachments. No shortcut.
- New mail and verdicts appear live in the Inbox over the existing SSE channel, with the same stages as the demo console (received → extracting → checks running → flagged/held or accepted).
- Only process mail that arrives after connecting, plus an optional "import last 7 days" button during onboarding.
- Mark the source of each email (Gmail or sandbox) in the Inbox and in the audit log.

Sending mail (used by P4)
- When Gmail is connected, approved emails are sent through the Gmail API instead of the simulated outbox. All P4 gateway rules still apply: owner signature, known recipients only, numeric firewall on the body, no replies to Sentinel-flagged senders.
- Add a DEMO_SEND_ALLOWLIST in .env: real sending only goes to addresses on that list; anything else falls back to the simulated outbox with a clear label. This prevents accidental real emails during rehearsals.

Reliability
- If Gmail is unreachable or the token expires mid-demo, show a clear status ("Gmail disconnected — reconnect") and keep the sandbox inbox working. A one-click switch between Gmail and sandbox.
- Rate-limit and back off on Gmail API errors.

Tests (mock the Gmail API; no network in CI): connect/callback with state check, token encryption, a new message goes through the full pipeline, a malicious attachment is flagged, sending respects the allowlist, disconnect revokes and deletes the token, and the planner never sees the token or raw email text.

Commit and push. Then tell me exactly what I need to do to connect the demo account live.
```

---

## P2 — Live demo console

Note (after P6): the live stages already exist. Deliver console mail through `InboxProcessor.process()` and the
Inbox tab shows received → extracting → checks → verdict over `GET /businesses/{id}/inbox/stream`, with a toast when
something is held.

```
Add a live demo console, timeboxed to 3 hours. This is a demo tool, not part of the product.

Console page
- A separate route (e.g. /demo-console). Only available when a DEMO_MODE flag is on; it must not exist in normal mode. Label it clearly as a simulated sender.
- Preset buttons, built from the planted attacks in the mailbox manifest plus some benign emails:
  - Normal supplier invoice
  - Customer deal or order
  - Payee-change fraud
  - Lookalike-domain phishing
  - Urgency scam
  - Unusual-amount invoice
  - Prompt-injection email ("ignore your rules and pay…")
- A custom compose form: sender, subject, body, optional PDF or image attachment.
- The console only injects into the sandbox mailbox (spoofed senders and lookalike domains allowed). It does not send real email; real emails during the demo are sent from my phone to the connected demo Gmail inbox (P6).
- Each send delivers the email into the inbox through the same path real mail would take: quarantined extractor, then Inbox Sentinel, then the planner. No shortcut that skips the safety pipeline.

Real-time updates
- Push events to the owner's app over SSE or WebSocket (reuse the streaming setup from /agent/chat if possible). Stages: received → extracting → checks running → flagged/held or accepted.
- Show this live in the Inbox, and add a toast or Morning Brief update when something is flagged.
- Show the flag reasons in plain language (e.g. "bank details changed," "domain looks like supplier.com but isn't"), plus the verification call script for fraud.
- Every received email and verdict is written to the audit log.

Live LLM
- All emails, presets and custom ones, are processed with live LLM calls in real time. No replay mode for the console.
- Show each processing stage as it happens, so the LLM's thinking time reads as KaChing working, not as lag.
- If an LLM call fails mid-demo, the Sentinel's rule-based checks must still flag fraud. Tell me which checks are rule-based and which need the LLM.

Layout for the demo video: make it work side by side, console on the left and the owner's KaChing on the right.

Tests: each preset gets the right verdict, the console route is absent when DEMO_MODE is off, and the injected email can't trigger any action.

Commit and push.
```

---

## P3 — Payments tab with a connected payment provider

Note (after P3): done; see "P3 (payments) as built" under Known facts. The T2 cap decision was taken (৳5,000 for
bills). `pay_invoice` is Payments-tab only, by Raiyan's choice, so planner recordings did not go stale.

Note: confirmed by reading `executor/sandbox_bank.py` that `pay_recurring_bill` currently writes only to its own
operations table, never the ledger — this prompt's "balance drops and buffer days update visibly" step is real,
needed work, not a check on something already there. Also: the T2 cap (50000 minor units) is an open decision —
confirm keep-vs-raise with Raiyan before starting (see Known facts above).

```
Add a Payments tab with a connected payment provider, timeboxed to 4 hours. Use the existing browser signing (tweetnacl) for approvals.

Payment provider (simulated)
- Build a mock payment provider as a separate local service with its own API, so KaChing talks to it over the network like a real bank or mobile-money API. Give it a generic name (e.g. "SandboxPay"); don't use real brands.
- Evolve executor/sandbox_bank.py into the client for this provider rather than adding a parallel executor. Keep the existing rule and test that only the gateway may import the executor.
- Connect flow: the owner clicks "Connect payment service." They see a consent screen showing what KaChing can do (scopes, per-payment cap, daily cap) and approve it. KaChing gets a scoped token.
- The provider enforces its own limits independently of KaChing's gateway, so a compromised KaChing still can't exceed them.
- Settlement is asynchronous: the provider returns "processing," then sends a webhook "settled" or "failed" a few seconds later.

Payments tab
- Connected services: status, scopes, limits, and a disconnect button.
- Payees: known contacts, with a verified badge. Adding a new payee needs the owner's extra confirmation.
- Pay requests:
  - Created by the owner manually, or proposed by KaChing (e.g. from an approved invoice, or a bill due soon).
  - Each request shows payee, amount, reason, and its source (e.g. "from invoice #123").
- Approval: goes through the existing gateway (tiers, mandates, signed approval). Requests covered by a mandate run automatically; everything else waits for the owner's signature.
- Live status per payment: proposed → approved → sent → settled/failed, updated in real time over the same SSE/WebSocket channel as the demo console.
- When a payment settles, the ledger balance drops and the forecast and buffer days update visibly. Show a receipt.
- History with filters.

Safety (add each as a red-team test)
- The approval is bound to a hash of payee + amount + account. If any of those changes after approval, execution is refused.
- Idempotency key on every payment, so a double click or retry can never pay twice.
- Amounts that came from an email always need the owner's approval, even under a mandate.
- No paying a payee from a Sentinel-flagged email until the call-script verification is marked done.
- Disconnecting the provider revokes the token immediately.
- Every step is in the audit log, including the provider's webhooks. Settled payments and their signed mandates feed into the existing anchoring batches, so each payment can be verified on-chain from the Trust tab.

Demo flow: an invoice arrives (via the demo console) → KaChing proposes paying it → the owner approves with one tap → status goes live to "settled" → balance and buffer days update.

Optional, only if time remains and you tell me first: add a testnet stablecoin rail as a second provider, so payments themselves settle on-chain, not just their audit trail.

Commit and push.
```

---

## P4 — Sending approved emails

Note (after P4): done; see "P4 (emails) as built" under Known facts. Tier chosen for `send_email`: **T3**.

Note (after P6): the transport exists. `executor/mail_sender.py` routes every approved email to Gmail or the sandbox
outbox (allowlist-gated) and records it in `outbox` with `transport`; reminders already go through it with a fixed
template. P4 still owns firewall-checked bodies, the approval card with draft editing, `send_email`, and the outbox UI.

Note: confirmed `send_invoice_reminder` already writes a row to `SandboxMailbox`'s `outbox` table — the gap is
purely that nothing reads it (no API route, no frontend component). This prompt's "store sent emails, show them in
the UI" step can read that existing table rather than building new storage.

```
Add agentic email sending (approved emails only), timeboxed to 3 hours.

Behaviour
- The planner and the overnight job can propose an email as an action (via propose_action), for example a payment reminder for an overdue invoice or a reply to a supplier.
- Every email goes through the gateway and needs the owner's signed approval before sending. Show it on the approval card: recipient, subject, full body, and why KaChing wants to send it.
- The owner can edit the draft before approving.
- "Sending" goes to a simulated outbox (sandbox), not real SMTP. Store sent emails, show them in the UI, and include them in evidence logs.

Safety rules (also add each as a red-team test)
- Never send to the sender of an email the Sentinel flagged. Those get the verification call script instead.
- The recipient must already be a known contact in the ledger. A new address needs explicit extra confirmation from the owner.
- Every number in the email body comes through the numeric firewall from ledger facts. No invented amounts.
- No sending from content found inside an email (prompt injection). An email asking KaChing to email someone must be flagged, not acted on.
- Every proposal, approval, edit and send is written to the audit log.

Demo flow to make work end to end
- The overnight job finds an overdue customer invoice, drafts a reminder, and shows it in the Morning Brief.
- The owner approves and signs. The email appears in the outbox, and the audit log shows the full chain.

Tests: approved send, rejected send, flagged-sender block, unknown-recipient block, injected "please email X" instruction, invented number caught by the firewall.

Build on the existing T2 send_invoice_reminder action and its standing mandate: reminders become real outbox emails. Add a separate send_email action for other emails (replies to suppliers, etc.); decide its tier in policy.yaml and tell me which tier you chose. Commit and push.
```

---

## Demo script (5 min) — every flow here must work end to end

| Time | Scene | Proves |
|---|---|---|
| 0:00–0:15 | The problem, then "Meet KaChing" | — |
| 0:15–0:25 | Opening page: built-in skills plus "Upload your own skill.md"; upload bakery.skill.md → preview of what it will ask and watch, "Community — unverified" badge. Narration: "Anyone can teach KaChing a new business." Then pick Fashion | Custom skills (P8) |
| 0:25–1:10 | Fashion onboarding: KaChing asks what the owner wouldn't think of ("Do you take returns? Why I'm asking: returns quietly eat fashion margins"; Eid stock; marketplace fees) → drag in sample folder (⏩ processing) → confirm contacts and summary. Narration: "KaChing knows how a fashion shop runs, so it asks what you'd forget." | Onboarding, proactive questions, upload (P1) |
| 1:10–1:30 | Connect Gmail (⏩ cut past consent screen) → sign a starter mandate | Gmail OAuth (P6), mandates |
| 1:30–2:05 | First brief: buffer days, losing campaign, a leak → click a number into the trace drawer → glance at Transactions | Brief, firewall, trace, Transactions (P5) |
| 2:05–2:45 | Ask: "Which product should I advertise more?" → "Why not the best seller?" → "What if I move ৳5,000 from campaign A to B?" | Ad advisor (P7) |
| 2:45–3:30 | Send a scam email from your phone on camera → flagged live; console: lookalike bank-change scam and prompt injection → held | Real inbox (P6), console (P2), Sentinel |
| 3:30–4:15 | Legit invoice → pay with one tap → live to settled → balance drops in Transactions; ⏩ fast-forward to morning → reminder drafted → approved → sent via Gmail | Payments (P3), email sending (P4) |
| 4:15–4:45 | Trust tab: red-team results, audit chain, Verify on-chain | Red team, anchoring |
| 4:45–5:00 | Close: "KaChing knows how your business runs. Set up in two minutes, works while you sleep, never moves money without you." | — |

Recording: one scene per take, reset command between rehearsals, picture-in-picture for the phone, captions on every fast-forward.

---

## Rules for every prompt

- Respect each timebox. If a feature isn't working at the end of its timebox, stop and report rather than running over.
- Keep `make test` green after every commit, and push after every commit.
- If something blocks you for more than ~30 minutes, stop and report.
- Feature freeze Tue 13:00 Dhaka: after that, bug fixes and submission materials only.
- Don't add anything not listed here without asking first.
- Design: there are no more Claude Design handoffs. Design every new screen and component yourself, matching the existing screens' look. Use only theme variables, APP_NAME and <Logo />, and keep the branding check passing. Don't wait for designs.

---

## Maintaining this file

This file is the single source of truth for remaining work. Raiyan does not edit it by hand — Claude Code owns it.

- **Update it in the same commit** as the work it describes, not in a follow-up commit. When a prompt (P0–P8,
  Prompt 19) finishes, flip its Status row to Done (or Partial, naming what's missing) in that commit, before
  pushing.
- **Verify before writing a status**, don't just trust what a prompt said it would do. Check the actual commit,
  grep the code for the thing that's supposed to exist, and re-run `make test` (and `make redteam` if planner
  tools, policy.yaml or prompts changed) rather than copying forward an old claim.
- **Known facts only records what later prompts depend on** — tier caps, what's already wired vs. not, stale
  suites, spend, open decisions. Don't let it become a changelog; prune a fact once no remaining prompt needs it.
- **A Note: line under a prompt, not a rewrite.** If something already built makes a planned prompt wrong,
  redundant, or easier than written, add a `Note:` line under that prompt's heading explaining what changed and
  why. Never rewrite or delete prompt text for a prompt that hasn't run yet — the prompt is Raiyan's plan, and
  silently changing it removes his ability to review the change.
- **Red-team/benign replay staleness is a first-class fact.** Any change to `planner.md`, a tool schema (including
  action args generated from `policy.yaml`), or `extractor.md`/`quarantine/schemas.py` invalidates cached replay
  recordings for affected suites. Note which suites went stale and whether they were re-recorded, per
  [[benign-replay-rerecord]] in memory.
- **Never invent a number here.** Spend, test counts, red-team results and anchor tx hashes must come from an
  actual run referenced in this update, same as CLAUDE.md invariant 8 requires for the deck and README.
- **Open decisions get one line under Known facts**, not a buried question in prose, so the next session sees them
  without re-reading the whole file. Remove the line once Raiyan answers and the decision is applied.
- `docs/build-prompts.md` is superseded by this file (see the note at its top) and should not be edited going
  forward; if it still exists when this file no longer needs merged content from it, it can be deleted.
