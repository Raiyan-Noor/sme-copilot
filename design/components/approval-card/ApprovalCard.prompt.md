Card for an action the copilot prepared that needs the owner's signature; use it in the approvals queue and inline in chat.

```jsx
<ApprovalCard
  title="Pay Fresh Farms invoice #2291"
  amount="$1,240.00" onAmountClick={openTrace}
  description="Matches the delivery on Oct 14. Paying today keeps your 2% early discount."
  facts={[{ label: 'Due', value: 'Oct 21' }, { label: 'From', value: 'Checking ··4410' }, { label: 'Saves', value: '$24.80' }]}
  limitNote="Within your $2,000 Ask first limit"
  meta="Prepared 9:14 am"
  onApprove={sign} onDecline={decline} />
```

- `status="waiting"` shows "Sign and approve" + "Decline". `executed`/`blocked` hide buttons and show `resolvedNote`.
- Always include `limitNote` so the owner sees which signed limit the action falls under.
- Blocked cards get a red hairline; keep the copy factual ("Blocked: over your $2,000 limit").
