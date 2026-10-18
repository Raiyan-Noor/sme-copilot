KPI tile with a big tabular figure; use it for the 2–4 headline numbers at the top of a page.

```jsx
<KpiTile label="Cash on hand" icon="wallet" value="$18,240"
  delta={{ label: '+$1,120', tone: 'good' }} caption="vs last Friday" onTrace={openTrace} />
<KpiTile size="md" label="Wasted this month" value="$340" delta={{ label: '3 subscriptions', tone: 'bad' }} />
```

- No border or background of its own; drop it inside a `Card` or a grid.
- `onTrace` turns the value into a `FactNumber`.
- Value is Public Sans Light (300), tabular — never bold.
- Delta always carries an icon and words. `good` is green; `bad` stays in text color — red is only for fraud and blocks.
