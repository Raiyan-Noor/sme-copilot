Data table (shadcn Table) for transactions, invoices and offers; define columns once and pass rows.

```jsx
<Table rowKey="id"
  columns={[
    { key: 'vendor', header: 'Supplier' },
    { key: 'due', header: 'Due' },
    { key: 'status', header: 'Status', render: r => <StatusPill size="sm" status={r.status} /> },
    { key: 'amount', header: 'Amount', align: 'right' },
  ]}
  rows={invoices} onRowClick={openInvoice} />
```

- Right-align money; figures are tabular so columns line up.
- Headers are sentence case, 12px, muted. No zebra stripes; hairline row borders and a hover wash.
- `density="compact"` for dense lists inside cards.
