Small floating confirmation (surface-raised, the one soft shadow) (shadcn Toast/Sonner) shown bottom-right after an action; you control mount and timeout.

```jsx
<Toast variant="success" title="Payment scheduled" description="$1,240.00 to Fresh Farms on Oct 18." action={{ label: 'Undo', onClick: undo }} onClose={close} />
<Toast variant="savings" title="Cancelled 2 subscriptions" description="You'll save $86 a month." />
```

- Titles are past tense and factual. One optional action.
- Auto-dismiss after ~5s; never for fraud — use `AlertBanner` instead.
- Position: fixed, bottom 24px, right 24px, stacked with 8px gap.
