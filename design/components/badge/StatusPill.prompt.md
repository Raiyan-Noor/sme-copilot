Pill showing the state of an agent action or an offer's fit; use it wherever status is shown — it always pairs an icon with a word.

```jsx
<StatusPill status="executed" />
<StatusPill status="waiting" />
<StatusPill status="blocked" />
<StatusPill status="fits" />
<StatusPill status="doesnt-fit" />
<StatusPill status="synthetic" />
```

- Fixed set: Executed, Waiting for approval, Blocked, Fits, Doesn't fit, Synthetic data.
- `label` overrides the word ("Blocked by limit"); the icon stays.
- `size="sm"` (20px) for dense tables; `md` (24px) default.
- Waiting for approval is gold text with a thin gold outline, no fill. Coral-red is reserved for Blocked. Doesn't fit is neutral, not an error.
