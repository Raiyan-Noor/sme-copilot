# KaChing owner app — UI kit

Click-through of the KaChing web app a shop owner opens each morning. Built from the design-system components (`window.KaChingDesignSystem_2fdbe1`) plus layout CSS in `kit.css`. Derived from the brief, not shipped software.

## Layout
Conversation-first, no dashboard pages (see readme → Layout).
- **Chat** (`chat.jsx`) — 720px column centred on the window. Morning brief first: fraud alert and two approval cards inside the message, then cash and an unused-tools note. Suggestions, composer, canned replies with FactNumbers.
- **Rail** (`rail.jsx`) — 280px, right edge: Cash on hand, Safe to spend, Found this month; links to the four detail views; shop.
- **Detail panel** (`detail-panel.jsx`, `detail-views.jsx`) — 560px from the right; the chat moves left. Views: **Cash, next 30 days** (chart + Coming up table), **Inbox** (invoices → invoice checks), **Financing**, **Trust** (signed limits, this month, what KaChing did).
- `data.js` — all synthetic data.

## Interactions
Click any dotted figure for its trace Sheet · Sign / Decline approvals in the brief (toast with Undo) · Keep payment blocked / Review invoice · rail links and chat buttons open the panel · × or Esc closes it · invoice rows drill in with a back button · suggestions and free text.
