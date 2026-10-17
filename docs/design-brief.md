# Design brief for Claude Design

Paste the **Prompt** section into Claude Design. The rest is reference for follow-up iterations.
Target: Next.js 16 + Tailwind + shadcn/ui + Recharts, so ask for designs that map to those components.

---

## Prompt

Design a simple, calm web app for an AI finance copilot used by the owner of a small shop. It must be judged in a
5-minute demo video, so clarity beats density: one main idea per screen, large readable numbers, generous spacing.
Desktop-first at 1440px, but every screen must also work on a phone.

**Product.** The copilot reads the shop's transactions, forecasts cash, finds wasted money, matches financing,
screens finance emails for fraud, and prepares actions. It can only act within limits the owner has signed, and
anything risky waits for the owner's one-tap signed approval. The core feeling: "I can trust this with my money."

**Visual direction.** Light theme, neutral off-white background, one deep green accent for money/safe states, amber
for warnings, red only for fraud and blocked actions. One sans-serif typeface; tabular numerals for all figures.
Rounded cards, thin borders, no gradients, no illustrations, no stock imagery. Icons from Lucide. Use shadcn/ui
patterns (Card, Badge, Button, Sheet, Dialog, Tabs, Table, Progress).

**Global layout.**
- Left sidebar: business switcher at top (shows business name and a "Skill Pack: Grocery" badge), then nav:
  Today, Ask, Cash flow, Financing, Inbox, Trust. An "Approvals" item with a count badge.
- Top bar: a small "Synthetic demo data" label, a simulated date with a "Fast-forward to tomorrow 7:00" button,
  and a model indicator chip (e.g. "Planner: GPT-5.6 · fallback ready").
- Every number in the app is clickable. Clicking opens a right-side drawer "Where this number comes from": the
  calculation in words, the formula, and a small table of the source transactions.

**Screens.**
1. **Today (Morning Brief).** Hero row: cash balance, runway in days, next shortfall date. Below: "Needs you today"
   (approval cards and fraud alerts), "Done overnight" (actions taken under signed limits, each with a "view log"
   link), "Coming up" (due payments, seasonal effects), "One thing to improve" (largest cost leak with yearly saving).
2. **Ask.** Chat with the copilot. Replies contain clickable numbers. When the copilot proposes an action, an inline
   action card appears with its status: Executed (green), Waiting for your approval (amber), or Blocked (red, with
   the rule that blocked it). Suggested prompts as chips above the input.
3. **Cash flow.** A 30/60/90-day toggle; a line chart of projected balance with a shaded uncertainty band, a dashed
   safety-buffer line, and a marker where the balance crosses it. Below: ranked fixes as cards (collect dues, shift
   a payable, cut a leak, short-term financing), each showing its effect on the shortfall and a "Prepare" button.
4. **Financing.** Product cards (3–6). Each shows product name, lender type, a Fits / Doesn't fit badge, a checklist
   of eligibility rules with pass/fail and a one-line reason, and the "repayment-safe amount". A "Readiness Passport"
   panel: a readiness band (e.g. Building / Ready), five factor bars, and "what would move you up". Footer
   disclaimer: the lender decides; this is not financial advice.
5. **Inbox.** A list of finance emails with category tags and risk flags. Selecting one shows the original email on
   the left and the copilot's findings on the right: extracted fields, red flags (lookalike domain, bank details
   changed, urgency, unusual amount), "Instructions to the assistant were detected and ignored" when relevant, and a
   prepared verification call script. Fraud items are visually unmistakable.
6. **Trust.** Three tabs. *Permissions*: four tiers as rows (Autonomous, Autonomous within limits, Needs your
   approval, Never automated) with the tools in each, editable caps, and a "Re-sign policy" button. *Audit log*: a
   table of every step (time, actor, tool, decision, provider/model) with a prominent "Verify chain" button that
   shows a green verified state. *Red-team*: attacks run vs. blocked, benign tasks completed, and a list of attacks
   with the defense that caught each.
7. **Approval sheet** (opens from any approval card): exact amount, payee, reason, risk flags, the facts it relies
   on, a cooling-off timer for first-time payees, and two buttons: "Sign and approve" and "Decline". After signing,
   show a brief signed confirmation with the mandate ID.

**States to include.** Empty states, loading skeletons for copilot replies, a "fell back to backup model" toast, and
a "Skill Pack switched to Fashion" moment where the business switcher changes to "Lina's Boutique" and the Today
screen's figures and leak types change.

**Sample content.** Use Maya's Corner Store, a neighbourhood grocery the week before a major holiday. Use realistic
but clearly fictional names. Currency USD.

---

## Reference: data shapes the UI will receive

```ts
type Fact = { id: string; display: string; unit: "money" | "days" | "percent" | "date" | "count";
              computedBy: string; sourceRowIds: string[] };

type ActionCard = { id: string; tool: string; tier: "T2" | "T3";
                    status: "executed" | "pending_approval" | "denied";
                    summary: string; amount?: Fact; payee?: string; reason: string;
                    riskFlags: string[]; deniedRule?: string; mandateId?: string };

type CopilotMessage = { role: "owner" | "copilot"; text: string;   // text contains {fact:id} placeholders
                        facts: Record<string, Fact>; actions: ActionCard[] };

type FinancingMatch = { productId: string; name: string; lenderType: string; fits: boolean;
                        rules: { label: string; passed: boolean; reason: string }[]; safeAmount?: Fact };

type InboxFinding = { emailId: string; category: string; riskFlags: string[];
                      instructionLikeTextDetected: boolean; extracted: Record<string, unknown>;
                      callScript?: string };

type AuditEntry = { seq: number; ts: string; actor: "owner" | "planner" | "gateway" | "executor" | "extractor";
                    tool?: string; decision?: string; provider?: string; model?: string; hash: string; prevHash: string };
```

## Handoff to the codebase

When the screens look right, export or hand off the code, put it in `frontend/`, and give Claude Code the build
prompt "Wire the Claude Design screens" from `docs/build-prompts.md`. Ask Claude Design for components that accept
the data shapes above as props, with mock data in a separate file, so wiring is a swap rather than a rewrite.
