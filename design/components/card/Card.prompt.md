The base grouping surface (shadcn Card) — a quiet step up from the page, no border or shadow; `improve` is the single "One thing to improve" card per page.

```jsx
<Card title="Cash this week" description="Updated 2 min ago" action={<Button variant="ghost" size="sm">See all</Button>}>
  …
</Card>
<Card variant="improve" title="Cancel two unused tools"
  footer={<Button>Prepare cancellation</Button>}>
  You pay $86 a month for software nobody has opened since June.
</Card>
```

- `default`: `surface-muted` fill, no border, no shadow, radius-lg (20px), 24px padding.
- `muted`: transparent, no side padding — a titled group separated by spacing only.
- `improve`: default fill with a thin gold outline and gold eyebrow (gold = needs you). Never a gold fill. At most once per screen.
