# KaChing — Claude Code prompts

Deadline: Tue Oct 20, 23:59 Beijing = **21:59 Dhaka**
Feature freeze: **Tue 13:00 Dhaka**
Last updated: Mon Oct 19, 05:35 Dhaka
Repo copy: `docs/dev/feature-plan.md` (this file is the master; replace the repo copy when it changes)

## Status

The original build plan (prompts 0–17) is fully built, including Prompt 16 (screens, SSE chat, tweetnacl signing, trace drawer, pack switcher, fast-forward, Trust tab) and Prompt 17 (on-chain anchoring with Merkle root, testnet transaction and verify). The features below are new work on top of it.

| # | Item | Status |
|---|------|--------|
| Prompts 0–17 | Original build plan | Done |
| Prompt 18 | Stretch 2: Monte Carlo what-if, marketing ROI, expansion planner | Dropped (P7 covers marketing ROI) |
| Prompt 19 | Evidence and docs: `make evidence` (currently a stub), Sol demo-profile recordings, Gemini recordings | Not built — run after P4, before the freeze |
| F1 | Document upload | Merged into F4 |
| F2 | Sending approved emails | Prompt ready (P4) |
| F3 | Live demo console | Prompt ready (P2) |
| F4 | Onboarding from zero | Prompt ready (P1) |
| F5 | Payments tab | Prompt ready (P3) |
| F6 | Product and ad knowledge in Skill Packs | Merged into P1 |
| F7 | Transactions tab | Prompt ready (P5) |
| F8 | Real Gmail inbox via OAuth (read + send approved emails) | Prompt ready (P6) |
| F9 | Ad advisor: discuss which product to advertise more | Prompt ready (P7) |
| F10 | Proactive "what you didn't think of" questions from the Skill Pack | Merged into P1 |
| F11 | Upload a custom skill.md on the opening page; open skills library | Prompt ready (P8) |
| F12 | Chat loading messages that show what KaChing is doing | Prompt ready (P0) |
| — | Correcting ledger entries | Dropped |

**Build order:** P0 → P1 → P8 → P7 → P5 → P6 → P2 → P3 → P4 → Prompt 19 (evidence). P0 is a quick fix, do it first. Prompt 19 must run before the freeze: the submission requires execution evidence. All build on Prompt 16's signing, SSE chat and real-data screens, which already exist. P8 follows P1 because it reuses the pack-driven onboarding. P7 uses the product and ad data onboarding imports. P5 comes early because uploads, payments and emails all show their results in the Transactions tab. P6 comes before P2 and P4 so the console and email sending can use the real inbox.

**Demo email plan:** the console injects sandbox attacks that real email can't fake (lookalike domains, spoofed senders); real emails are sent live from your phone to the demo Gmail inbox.

**Manual setup before P6 (you, ~15 min):** create a fresh Gmail account for the demo shop; create a Google Cloud project; enable the Gmail API; configure the OAuth consent screen in testing mode; add the demo Gmail as a test user; create an OAuth client (web app) with redirect URI `http://localhost:<backend port>/inbox/gmail/callback`; put the client ID and secret in `.env`. No paid services needed.

**Demo story:** a new business sets up KaChing in under 2 minutes → uploads files → connects its inbox → gets its first brief → attacks arrive live from the console and get flagged → an invoice is paid with one tap → a reminder email is approved and sent.

## Known facts about the build (answered Mon 05:32)

Tiers in policy.yaml:
- **T1** (autonomous, read/compute only): `get_*`, `list_*`, `explain_fact`, `match_financing`, `get_passport`; system-only `anchor` (testnet only, 12 runs per hour).
- **T2** (signed standing mandate, max 90 days; over-cap is denied, not escalated):
  - `send_invoice_reminder`: up to 50000 minor units, allow-listed customers, 1 per customer per 3 days.
  - `pay_recurring_bill`: up to 50000 minor units, allow-listed payees.
- **T3** (owner signs the exact payload, approval expires after 2 days): `submit_loan_application`, `change_payee_details` (needs a call script), `delay_supplier_payment`, `send_supplier_message`, `cancel_subscription`.
- **T4** (never executed; analysis only, logged as a violation): `large_debt`, `hiring_or_firing`, `pricing_change`, `deal_commitment`.

Also known: products are tracked individually; untrusted-provenance arguments force T3; a statement-upload endpoint exists.

Anchoring: `docs/results/anchors.json` holds one real Sepolia transaction (batch `anc-000001`, block 11942865) that verifies.

## Do now (5 min)

```
Commit and push the two untracked RPC replay files in backend/data/replay/rpc/ from the make anchor run.
```

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
6. Rules: KaChing suggests 1–2 starter mandates based on the data, using the existing T2 tools (`pay_recurring_bill` for regular bills, `send_invoice_reminder` for overdue customers), e.g. "pay your internet and electricity bills automatically" or "remind customers about overdue invoices". Suggested amounts must stay within the policy.yaml T2 caps. The owner edits and signs them, or skips this.
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
- Approval: goes through the existing gateway (tiers, mandates, signed approval). Recurring bills use the existing T2 `pay_recurring_bill` and run automatically under a mandate. Add a `pay_invoice` tool for one-off supplier invoices as T3 (owner signs the exact payload), and add it to policy.yaml.
- Over-cap T2 requests are currently denied outright. In the Payments tab, show the denial clearly and offer "Ask me to approve this one" which re-proposes it as T3. Don't change the gateway's deny rule itself.
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

Build on the existing T2 send_invoice_reminder action and its standing mandate: reminders become real outbox emails. For other emails (replies to suppliers, etc.), reuse the existing T3 `send_supplier_message` tool rather than adding a new one; extend it to customers if needed and keep it T3. Commit and push.
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