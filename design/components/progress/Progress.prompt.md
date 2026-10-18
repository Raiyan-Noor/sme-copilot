Progress (plain bar) and FactorBar (labelled factor with value, hint and threshold tick); use FactorBar to explain why an offer fits or how much of a signed limit is used.

```jsx
<Progress value={62} label="Limit used" />
<FactorBar label="Monthly repayment vs cash buffer" value={38} valueLabel="38%" hint="Under 50% is comfortable" threshold={50} />
<FactorBar label="Spent of approval limit" value={1240} max={2000} valueLabel="$1,240 of $2,000" tone="gold" />
```

- Tones: `brand` default, `teal` for chart-like highlights, `gold` for savings, `danger` for risk over threshold, `neutral`.
- Value text is always present; the bar is never the only signal.
