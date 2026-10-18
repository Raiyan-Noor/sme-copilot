A clickable figure with a dotted underline that opens the trace drawer; use it for every number the copilot computed so the owner can check the math.

```jsx
<p className="kc-body">
  You can cover payroll with <FactNumber source="Bank feed, 3 accounts" onClick={openTrace}>$4,280</FactNumber> to spare.
</p>
<div className="kc-display-number"><FactNumber onClick={openTrace}>$18,240</FactNumber></div>
```

- Inherits font size, weight and family, so it works inline in body copy and inside a display number.
- Dotted underline at rest, soft green wash on hover, solid focus ring on keyboard focus.
- Pair with `Sheet` for the trace: inputs, formula, source and timestamp.
