Right-side drawer (shadcn Sheet); its main job is the trace drawer that opens from a FactNumber and shows how a figure was computed, step by step.

```jsx
<Sheet open={open} onOpenChange={setOpen} title="Cash on hand" description="As of Oct 18, 9:02 am"
  footer={<Button variant="secondary" iconLeft="download">Export trace</Button>}>
  <TraceStep label="Checking ··4410" source="Bank feed, synced 9:02 am" value="$14,980" />
  <TraceStep op="+" label="Savings ··2208" source="Bank feed" value="$4,100" />
  <TraceStep op="−" label="Pending card charges" source="3 transactions" value="$840" />
  <TraceStep op="=" label="Cash on hand" value="$18,240" emphasis />
</Sheet>
```

- Closes on Esc and scrim click. `contained` keeps it inside a positioned parent (previews, embedded panels).
- `TraceStep` rows: operator gutter, label + source, tabular value. Mark the result row `emphasis`.
