Full-width banner (shadcn Alert) for suspected invoice fraud or a neutral notice; place it at the top of the affected page or card.

```jsx
<AlertBanner variant="fraud" title="This invoice's bank details changed"
  actions={<><Button variant="destructive" size="sm" iconLeft="ban">Block payment</Button><Button variant="secondary" size="sm">Call supplier</Button></>}>
  Northside Packaging sent account ··8812. Their last 14 invoices used ··3307. I paused payment until you check.
</AlertBanner>
<AlertBanner variant="info" title="Bank feed reconnected">Transactions after Oct 12 are now included.</AlertBanner>
```

- Every banner carries an icon and an eyebrow word, never color alone.
- `fraud` uses role="alert"; reserve it for fraud. Use `info` for everything else.
- State what happened, what KaChing did, and what the owner can do. No exclamation marks.
