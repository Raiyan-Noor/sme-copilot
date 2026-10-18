# KaChing Design System

KaChing is an AI finance copilot for small shop owners — bakeries, cafés, salons, corner stores. It watches cash, finds wasted money, matches financing offers, catches invoice fraud, and **acts only within limits the owner has signed**. The product should feel like a conversation with a trusted advisor, not a dashboard: calm, quiet, dark. **Dark theme only.**

## Sources
- `uploads/KaChing Growth Logo.png` — the only provided asset (1254×1254 PNG: gold coin, teal growth arrow, deep-teal swoosh, navy "Ka" + green "Ching" wordmark). Cropped into `assets/`.
- Written brief from the user (brand colors sampled from the logo, token names, type direction, component list, voice). No codebase, Figma or product screenshots were provided — every screen and component here is derived from that brief.

## Products
- **Owner web app** — the single surface: a conversation with the advisor. The morning brief opens the day; stats sit in a right rail; cash, inbox, financing and trust open as a detail panel. See `ui_kits/app/`.

---

## Content fundamentals

**Voice:** a trusted advisor talking to a busy shop owner. Plain, calm, short sentences. Numbers first, then what it means, then what to do.

- **Person:** the copilot speaks as "I" ("I paused the payment"). It addresses the owner as "you". Product chrome refers to the product as "KaChing" ("What KaChing did").
- **Casing:** sentence case everywhere — page titles, buttons, tabs, table headers. Never Title Case, never ALL CAPS.
- **Buttons:** verb first, specific. "Sign and approve", "Prepare reminder", "Keep payment blocked", "Prepare application". Never "Submit", "OK", "Click here", "Learn more".
- **No** exclamation marks, emoji, hype, or jargon ("AI-powered", "unlock", "insights", "crushing it").
- **Status words are fixed:** Executed · Waiting for approval · Blocked · Fits · Doesn't fit · Synthetic data.
- **Money:** always `$1,240.00` in tables and approvals; whole dollars (`$18,240`) in KPIs and chat. Account numbers as `··4410`. Dates as `Oct 21`. Times as `9:14 am`.
- **Bad news:** state what happened, what KaChing did, what the owner can do. "Invoice #7710 asks for account ··8812. Their last 14 invoices used ··3307. I paused the $2,980.00 payment until you check with them."
- **Toasts:** past tense, factual. "Payment scheduled", "Reminder sent".
- **Limits copy** names the signed limit: "Within your $2,000 Ask first limit".

| Write | Don't write |
|---|---|
| You can cover payroll with $4,280 to spare. | Great news! Your cash flow is looking healthy 🎉 |
| Three tools cost $86 a month. Nobody uses them. | Unlock AI-driven savings opportunities |
| I paused this payment. The bank details changed. | Oops! Something looks fishy!! |

## Visual foundations

**Mood.** A quiet room, not a cockpit. The advisor's words carry the screen; UI recedes. No heavy cards, borders or shadows — things are separated by spacing and by subtle surface steps.

**Color (dark only).** Three navy-tinted charcoal surfaces from the logo navy: `--surface #0F141A` (page), `--surface-muted #151C24` (groups, cards, chat panel, sheet), `--surface-raised #1B2430` (controls, inset fact blocks, owner bubble, toast). `--border #283340` is a soft line used sparingly (table rows, dashed trace steps) — never to box content. Text `#E6ECF1` (13.1–15.5:1), muted `#93A1AE` (5.9–7.0:1) on all three surfaces.
- **Green.** `--brand-primary #02A27D` is a lighter logo green for text, links, icons, active indicators, chart-1 and the focus ring (4.8:1 on raised, 5.7:1 on surface). The primary button fill is the logo green `#01775A` (`--kc-green-fill`) with `--on-brand` white text (5.5:1). `--brand-primary-soft #132A27` is a wash for hover/active only.
- **Gold `#F9A415` is the only warm color and means "needs you"** — waiting for approval, decisions pending. Text, icons and thin outlines (`--kc-gold-line`, 45% alpha) only; never a card, button or banner fill. `--warning` is gold; there is no separate warning color.
- **Success `#4FBF8B`** means done or money saved (Executed, savings badges, positive deltas, savings toasts).
- **Danger `#F07B70`**, a softened coral-red, is only for fraud and blocked actions. Negative deltas and money out stay in text color.
- **Charts:** chart-1 brand green for the main line, chart-2 muted teal `#5E9C98` for secondary series, chart-3 `#6B7A89` dashed (4 5) for the safety buffer. Gridlines `--border` at 60%. Area fills ≤8% opacity.

**Type.** Two families. **Newsreader** (`--font-advisor`, 19/30, 400) is used only when the advisor speaks — chat messages and advisor quotes. That alone makes the product feel like a conversation. **Public Sans** (`--font-display` and `--font-body`) for everything else: UI, labels, tables, numbers. Large display numbers are Public Sans **Light 300**, never bold. All figures tabular (`tnum lnum`, set globally). Seven styles: display number 48/56 300, page title 26/34 400, section title 17/24 500, advisor 19/30 serif, body 15/22, label 13/18 500, caption 12/16 muted. Classes `.kc-display-number`, `.kc-page-title`, `.kc-section-title`, `.kc-advisor`, `.kc-body`, `.kc-label`, `.kc-caption`. Weights stay at 300–500; 600 is rare.

**Spacing & layout.** 4px base (`--space-1` … `--space-16`). Groups pad 24px, gaps 24px, 24px between chat messages, 32px panel gutter. Screen layout is covered in **Layout** below.

**Corners.** Soft: `--radius-sm 8px` inputs, small badges · `--radius-md 14px` toasts, inset blocks · `--radius-lg 20px` groups, banners, approval cards, owner bubble · `--radius-full` buttons, pills, nav items, chips, composer.

**Groups (Card).** `surface-muted`, no border, no shadow. `muted` variant is transparent — a titled group held together by spacing. The improve card adds a thin gold outline (it needs a decision). At most one per screen. No colored left-border accents.

**Elevation.** Surface steps do the work. `--shadow-1` is `none`. `--shadow-2` (soft, black 45%) only for floating layers: sheet and toast.

**Focus.** One ring everywhere: 2px solid `--focus-ring` (= brand-primary), 2px offset. Never a glow.

**Backgrounds & imagery.** Flat dark surfaces. No gradients, textures, patterns or photography. The logo's gradients stay inside the logo.

**Motion.** Quiet and unhurried. `--ease-standard` cubic-bezier(0.2,0,0,1); 140ms hover/color, 220ms fades and toasts, 320ms sheet slide (24px + fade). No bounces or celebration. Respects `prefers-reduced-motion`.

**Hover / press.** Primary: fill lightens a step (`#017F60`), press darkens (`#016B51`), 1px translateY. Secondary: raised → `--kc-ink-3`. Ghost and nav: soft wash. Table rows: raised wash. FactNumber: dotted underline turns green over the green wash.

**Borders.** Rare. `--border` for table rows and dashed trace steps; `--border-strong #6B7A89` (3.6:1) for dashed "synthetic" pills and the trace total line. Dashed means "synthetic" or "computed".

**Transparency.** Only the sheet scrim (near-black 64%) and the semantic washes/gold line. No glassmorphism.

## Layout

KaChing is conversation-first. There are no dashboard pages and no navigation sidebar. Three regions, three tokens:

- **Chat** — `--chat-column 720px`. Always the centre of the screen: a single column centred on the **full window** (not on the space left of the rail), on `--surface`. Never a side panel, drawer or floating widget. The day opens with the **morning brief** as the first message; alerts and approval cards arrive inside it as attachments. Composer and suggestion chips dock at the bottom of the same column. Logo sits top-left of the window.
- **Stats rail** — `--rail-width 280px`, pinned to the right edge, page surface, no divider. Quiet: up to three traceable figures (KpiTile md) and links to the bigger views, shop identity at the foot. No charts, tables or cards.
- **Detail panel** — `--detail-width 560px`, `--surface-muted`, no shadow. Bigger views — cash chart, upcoming payments table, financing, inbox, trust — open here. It slides in from the right over the rail (320ms, `--ease-standard`) and the chat moves left to recentre in the space that's left; closing (×, Esc) returns everything. One panel at a time; drill-downs (an invoice) replace the panel body with a back button.
- **Sheet** — the trace drawer behind every FactNumber stays the only overlay (scrim + `--shadow-2`).
- **Narrow windows** (under 1100px): the rail hides, the chat fills the width less 24px gutters, and the detail panel floats over the chat with `--shadow-2`.

## Iconography

- **Lucide**, 1.5px stroke, round caps/joins, `currentColor`. Pinned `lucide@0.460.0` from unpkg; the `Icon` component loads it lazily. Sizes: 16 next to labels/pills, 20 default, 24 empty states.
- Common: `wallet`, `coins` (savings), `receipt`, `shield-alert` (fraud), `shield-check` (limits), `pen-line` (sign), `ban` (blocked), `circle-check` (executed), `clock` (waiting), `flask-conical` (synthetic data), `trending-up/down`, `landmark` (financing), `message-square` (chat).
- No emoji. No unicode glyphs as icons (the `··` in account numbers is a text convention, not an icon). No custom SVG icons.
- The only brand imagery is the logo (`assets/`). No illustrations were provided; don't invent any.

## Logo use
- On dark use `assets/logo-full-dark.png` and `assets/logo-wordmark-dark.png` — the navy "Ka" recolored to text off-white and "Ching" to brand-primary so both read on the surfaces. The coin, arrow and swoosh are unchanged. `assets/logo-mark.png` (coin + arrow, transparent) works on dark as-is: the advisor avatar and small spaces.
- The original light lockups (`logo-full.png`, `logo-wordmark.png`, `logo-original.png`) are kept for light contexts outside the product only; the navy wordmark is 1.2:1 on the dark surface.

---

## Index
- `styles.css` — entry point; `@import`s only.
- `tokens/` — `colors.css`, `typography.css` (Google Fonts import + type classes), `spacing.css` (space, radii, shadows, motion, layout), `base.css` (resets, links, focus).
- `components/<name>/` — `.jsx` + `.d.ts` + `.prompt.md` + `.css` + one `@dsCard` card each.
- Token names are unchanged from the light version; additions: `--font-advisor` (+ `--type-advisor-*`) and the layout widths `--chat-column`, `--rail-width`, `--detail-width` (these replace `--sidebar-width` and `--content-max`). Dark-ramp primitives are `--kc-ink-*`, `--kc-mist*`, `--kc-green-*`.
- `guidelines/` — foundation specimen cards (Colors, Type, Spacing, Layout, Brand).
- `ui_kits/app/` — owner web app: centred chat, stats rail, detail panel (`index.html`).
- `assets/` — logo crops.
- `thumbnail.html`, `SKILL.md`.

### Components
Namespace `window.KaChingDesignSystem_2fdbe1`. shadcn/ui mapping in brackets.
- **Button** [Button] — primary, secondary, ghost, destructive; sm/md/lg; icon; loading.
- **Badge** [Badge] — neutral, brand, savings (green), outline.
- **StatusPill** [Badge] — Executed, Waiting for approval, Blocked, Fits, Doesn't fit, Synthetic data.
- **KpiTile** — big tabular KPI with delta.
- **Card** [Card] — default (surface step), muted (spacing only), improve (thin gold outline).
- **FactNumber** — clickable figure, dotted underline, opens the trace Sheet.
- **ApprovalCard** — prepared action awaiting signature.
- **AlertBanner** [Alert] — fraud, info.
- **TierRow** — signed permission tier with tools.
- **Table** [Table] — columns + rows, right-aligned tabular money.
- **Tabs** [Tabs] — underline tabs with counts.
- **Toast** [Toast/Sonner] — default, success, savings, danger.
- **Sheet** [Sheet] — side drawer; **TraceStep** rows for the trace drawer.
- **ChatBubble** — owner (raised bubble, sans), copilot (unboxed serif).
- **Progress** [Progress] and **FactorBar** — plain bar and labelled factor bar.

### Intentional additions
- **Icon** — wrapper that renders Lucide at the brand 1.5px stroke without an npm dependency.
- **TraceStep** — the row primitive the trace drawer needs; the brief's Sheet/Drawer has no content model otherwise.

### Font note
Fonts load from Google Fonts (Newsreader, Public Sans) via `@import`; no font binaries are shipped. Swap in licensed files if the brand adopts a different face.
