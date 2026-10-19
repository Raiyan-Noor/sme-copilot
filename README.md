# KaChing: acts only within your signed limits

KaChing is an AI finance agent for small businesses. It reads the bank statements, sales, invoices and inbox of a
corner shop or a clothing store, then briefs the owner every morning: cash on hand, how long it lasts, money
leaking out, invoices to chase, and which financing the business could safely take on. It can act too, but only
inside limits the owner has signed with a key that never leaves their browser. Small reminders run under a signed
standing limit with hard caps. Payments, emails and loan applications wait for the owner to sign the exact payload,
and nothing outside the policy exists as a tool at all. The model proposes and code decides. Every number on screen
is computed in code and traces to its source rows; untrusted email and documents never reach the planner as text.
Every step goes into a hash-chained audit log whose head is anchored on an Ethereum testnet.

FinTechathon 2026, International Track, Topic E. All data is synthetic: **Maya's Corner Store** (grocery) and
**Lina's Boutique** (fashion). The codename `sme-copilot` is used for the repo and packages only.

## Documentation

| Document | What it covers |
|---|---|
| [docs/technical.md](docs/technical.md) | Architecture, agent loop, Numeric Firewall, quarantine and Sentinel, gateway and tiers, signing, Skill Packs, anchoring, payments, Gmail, forecast and ad advisor |
| [docs/security-self-assessment.md](docs/security-self-assessment.md) | Tiers, tools and caps; how each is enforced; red-team results; known risks |
| [docs/evidence/index.md](docs/evidence/index.md) | Execution evidence: audit log and chain check, testnet anchors, red-team, tests, outboxes, payments, LLM spend |
| [docs/skills/FORMAT.md](docs/skills/FORMAT.md), [skills/README.md](skills/README.md) | The skill.md format and the open skills library |
| [CLAUDE.md](CLAUDE.md) | The nine invariants the code must uphold |

## Quick start

Requirements: Python 3.12, Node.js 20+, GNU make (on Windows: `mingw32-make`, or `make` from choco/winget).

```bash
cp .env.example .env      # then set DEMO_PASSCODE at least; see "Environment" below
make setup                # backend/.venv + pip install, npm install
make demo                 # API :8000, SandboxPay :8100, web app :3000, demo console on; prints the URLs
```

Open http://localhost:3000 and enter `DEMO_PASSCODE`. Maya's Corner Store and Lina's Boutique are loaded from the
deterministic seed on first start. To start a business from zero, choose "Start fresh" on the opening page.

| Command | What it does |
|---|---|
| `make demo` | Stops stale servers on :8000/:8100/:3000 first, then starts everything with `DEMO_MODE=true` and `NEXT_PUBLIC_DEMO_MODE=true` (the live demo console at `/demo-console`) |
| `make dev` | Same servers without forcing demo mode (uses `.env` as is) |
| `make demo-reset` | Deletes businesses created by onboarding rehearsals; seeded businesses stay (same as `make reset-demo`) |
| `make test` | Every pytest suite in replay mode (no keys, no network), plus the branding check and frontend types check |
| `make redteam` | Attack and benign suites for every recorded provider; writes `docs/results/redteam.json` |
| `make evidence` | Offline: exports the audit log and verifies the chain, re-verifies the testnet anchors, collects red-team, tests, outboxes, payments and LLM spend into `docs/evidence/` |
| `make anchor` | Anchors the audit head now on the live testnet and writes `docs/results/anchors.json` (manual; needs `ANCHOR_*`; stop the API first) |
| `make seed` | Regenerates both synthetic businesses and the mailbox (deterministic) |
| `make validate-skill FILE=...` | Checks a skill.md the way an upload does |
| `make openapi` | Exports `docs/openapi.json` and regenerates `frontend/lib/types.ts` |

Without any LLM key the app still runs: replayed answers are used where recorded, and the planner and brief fall back
to template text built from the computed facts.

## Environment

Copy `.env.example` to `.env` (gitignored). Never commit real keys.

| Variable | Needed for | Notes |
|---|---|---|
| `DEMO_PASSCODE` | Everything | Every API route except health, docs and signed callbacks requires it. Unset means every protected route returns 503 (fails closed). |
| `ALLOWED_ORIGINS` | Browser access | CORS allow-list, e.g. `http://localhost:3000`. |
| `NEXT_PUBLIC_API_URL` | Frontend | Where the browser calls FastAPI, e.g. `http://localhost:8000`. |
| `OPENAI_API_KEY`, `GEMINI_API_KEY` | Live answers | OpenAI is primary; Gemini Flash is the fallback. |
| `LLM_PROFILE` | Model choice | `dev` (Terra everywhere) or `demo` (Sol for planner and brief). |
| `LLM_REPLAY` | Record/replay | `record`, `replay` or `off`. Tests always force `replay`. |
| `LLM_BUDGET_USD` | Spend cap | Local hard cap; past it the adapter switches to Gemini. |
| `ANCHOR_RPC_URL`, `ANCHOR_PRIVATE_KEY`, `ANCHOR_CHAIN_ID`, `ANCHOR_EXPLORER_URL`, `ANCHOR_BATCH_SIZE`, `ANCHOR_REPLAY` | Testnet anchoring | Throwaway faucet-funded key. Chain ID must be 11155111 (Sepolia) or 84532 (Base Sepolia); anything else refuses to start. Set `ANCHOR_REPLAY=record` on a server that should anchor live. |
| `GMAIL_CLIENT_ID`, `GMAIL_CLIENT_SECRET`, `GMAIL_REDIRECT_URI`, `GMAIL_TOKEN_KEY` | Real inbox | OAuth web client, consent screen in testing mode, demo account as test user. Token key encrypts refresh tokens at rest. |
| `DEMO_SEND_ALLOWLIST` | Real email sending | Only these addresses ever receive real mail; everything else goes to the labelled sandbox outbox. |
| `SANDBOXPAY_CLIENT_SECRET`, `SANDBOXPAY_TOKEN_KEY`, `SANDBOXPAY_URL`, `SANDBOXPAY_SETTLE_SECONDS` | Payments tab | Shared by the app and the simulated provider. |
| `DEMO_MODE`, `NEXT_PUBLIC_DEMO_MODE` | Demo console | `make demo` sets both to `true` for that run. |
| `SKILL_LIBRARY_SIGNING_KEY` | Re-signing built-in skills | Maintainers only; never needed at run time. |

## Deployment

The backend and SandboxPay ship as one image (`backend/Dockerfile`); the frontend is a standard Next.js build.

1. On the server, create `.env` from `.env.example`. Set a strong `DEMO_PASSCODE`, `ALLOWED_ORIGINS` to the
   frontend's public origin, `GMAIL_REDIRECT_URI` to `https://<api-host>/inbox/gmail/callback` (and add it to the
   OAuth client), and `SANDBOXPAY_URL=http://sandboxpay:8100`.
2. `docker compose up -d --build` starts `backend` on :8000 and `sandboxpay` on :8100, with `backend/data` mounted
   as a volume (tenants, audit log, anchors, replay cache). Put both behind HTTPS.
3. Frontend: in `frontend/`, set `NEXT_PUBLIC_API_URL=https://<api-host>` (and `NEXT_PUBLIC_DEMO_MODE=true` for the
   recording build), then `npm ci && npm run build && npm start`, or deploy the folder to any Next.js host with the
   same variables.
4. Check `https://<api-host>/health`, then open the frontend and sign in with the passcode.

CI (`.github/workflows/ci.yml`) runs `make setup` and `make test` in replay mode with no API keys, and lints and
builds the frontend.

## Red team and evidence

```bash
make redteam      # replays every recorded attack and benign case per provider -> docs/results/redteam.json
make anchor       # live: anchor today's audit head on Sepolia -> docs/results/anchors.json (stop the API first)
make evidence     # offline: everything above plus tests, outboxes, payments and spend -> docs/evidence/
```

Recording new cases costs money and needs keys: `python scripts/redteam.py --record --provider openai` (dev
profile), `--provider openai-demo` (Sol), or `--provider gemini` (the fallback subset). Results quoted anywhere in
the docs come from these files, never typed by hand.
