Small soft-cornered label (shadcn Badge) for tags, counts and savings callouts; use StatusPill instead for action status.

```jsx
<Badge>Supplier</Badge>
<Badge variant="brand">Copilot</Badge>
<Badge variant="savings">Saves $340 a month</Badge>
<Badge variant="outline">Updated 2 min ago</Badge>
```

- `savings` is green (money saved). Gold never appears on badges — it is reserved for "needs you".
- No borders except `outline`. Radius `--radius-sm` (8px); pills (full radius) are for status only.
