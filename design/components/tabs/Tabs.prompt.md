Underline tabs (shadcn Tabs) for switching views within a page; render the panel yourself based on the value.

```jsx
const [tab, setTab] = React.useState('open');
<Tabs value={tab} onValueChange={setTab} items={[
  { value: 'open', label: 'Open', count: 6 },
  { value: 'paid', label: 'Paid' },
  { value: 'flagged', label: 'Flagged', count: 1 },
]} />
```

- Active tab: navy label, 2px green underline. Inactive: muted label.
- Labels are short nouns in sentence case. Counts are tabular.
