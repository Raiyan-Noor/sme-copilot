function InboxView({ ctx }) {
  const { Tabs, Table, StatusPill, AlertBanner, Button } = window.KaChingDesignSystem_2fdbe1;
  const d = window.KC_DATA;
  const [tab, setTab] = React.useState('open');
  const count = (t) => d.invoices.filter((i) => i.tab === t).length;
  const rows = tab === 'all' ? d.invoices : d.invoices.filter((i) => i.tab === tab);
  return (
    <div className="kit-stack">
      {ctx.fraudOpen && tab !== 'flagged' ? (
        <AlertBanner variant="fraud" title="1 invoice is on hold" actions={<Button variant="secondary" size="sm" onClick={() => setTab('flagged')}>Show flagged</Button>}>
          Northside Packaging #7710 changed bank details. Payment stays blocked until you confirm.
        </AlertBanner>
      ) : null}
      <div className="kit-sec">
        <Tabs value={tab} onValueChange={setTab} items={[
          { value: 'open', label: 'Open', count: count('open') },
          { value: 'flagged', label: 'Flagged', count: count('flagged') },
          { value: 'paid', label: 'Paid' },
          { value: 'all', label: 'All' },
        ]} />
        <Table rowKey="id" onRowClick={ctx.setInvoice} columns={[
          { key: 'vendor', header: 'Supplier', render: (r) => <div><div style={{ fontWeight: 500 }}>{r.vendor}</div><div className="kc-caption" style={{ color: r.status === 'blocked' ? 'var(--danger)' : undefined }}>{r.inv} · {r.check}</div></div> },
          { key: 'status', header: 'Status', render: (r) => <StatusPill size="sm" status={r.status} /> },
          { key: 'amount', header: 'Amount', align: 'right' },
        ]} rows={rows} empty="No invoices here." />
      </div>
    </div>
  );
}

function InvoiceBody({ inv }) {
  const { AlertBanner, TraceStep, StatusPill } = window.KaChingDesignSystem_2fdbe1;
  const fraud = inv.status === 'blocked';
  return (
    <div className="kit-stack" style={{ gap: 20 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <StatusPill status={inv.status} />
        <span className="kc-display-number" style={{ fontSize: 32, lineHeight: '38px' }}>{inv.amount}</span>
      </div>
      {fraud ? <AlertBanner variant="fraud" title="Bank details changed">Requested account ··8812. Previous 14 invoices: ··3307. The email came from northside-packing.co, not northsidepackaging.com.</AlertBanner> : null}
      <div>
        <h3 className="kc-section-title" style={{ marginBottom: 4 }}>Checks</h3>
        <TraceStep label="Supplier known" source="23 invoices since 2023" value={<StatusPill size="sm" status="fits" label="Pass" />} />
        <TraceStep label="Amount in usual range" source="Median $2,710" value={<StatusPill size="sm" status="fits" label="Pass" />} />
        <TraceStep label="Bank account matches history" source="Compared to last 14 invoices" value={fraud ? <StatusPill size="sm" status="blocked" label="Fail" /> : <StatusPill size="sm" status="fits" label="Pass" />} />
        <TraceStep label="Matches a purchase order" source={fraud ? 'PO #1176' : 'PO #1180'} value={<StatusPill size="sm" status="fits" label="Pass" />} />
      </div>
      <div className="kc-caption">Received {inv.received}. Due {inv.due}.</div>
    </div>
  );
}

function FinancingView({ ctx }) {
  const { Card, StatusPill, FactorBar, Button, AlertBanner } = window.KaChingDesignSystem_2fdbe1;
  const d = window.KC_DATA;
  return (
    <div className="kit-stack" style={{ gap: 16 }}>
      <AlertBanner variant="info" eyebrow="How this works" title="KaChing compares offers. It never applies.">
        Taking on debt is set to Never in your limits. I can prepare the paperwork; you send it yourself.
      </AlertBanner>
      {d.offers.map((o) => (
        <Card key={o.id} variant="muted" eyebrow={o.product} title={o.lender} action={<StatusPill status={o.fit} />}
          footer={o.fit === 'fits'
            ? <Button size="sm" iconLeft="file-text" onClick={() => ctx.toast({ title: 'Application drafted', description: `${o.lender}. Review it before you send.` })}>Prepare application</Button>
            : <Button size="sm" variant="ghost" onClick={() => ctx.ask(`Why doesn't ${o.lender} fit?`)}>Ask why in chat</Button>}>
          <dl className="kit-terms" style={{ gridTemplateColumns: 'repeat(4,minmax(0,1fr))' }}>
            <div><dt>Amount</dt><dd className="kit-terms__big">{o.amount}</dd></div>
            <div><dt>APR</dt><dd>{o.apr}</dd></div>
            <div><dt>Monthly</dt><dd>{o.monthly}</dd></div>
            <div><dt>Term</dt><dd>{o.term}</dd></div>
          </dl>
          <div className="kit-stack" style={{ gap: 12, marginTop: 16 }}>{o.factors.map((f, i) => <FactorBar key={i} {...f} />)}</div>
        </Card>
      ))}
    </div>
  );
}

function TrustView({ ctx }) {
  const { TierRow, Button, FactorBar, StatusPill } = window.KaChingDesignSystem_2fdbe1;
  const d = window.KC_DATA;
  return (
    <div className="kit-stack" style={{ gap: 40 }}>
      <section className="kit-sec" style={{ gap: 4 }}>
        <div className="kit-sechead">
          <div><h3 className="kc-section-title">What KaChing may do</h3><div className="kc-caption" style={{ marginTop: 4 }}>Signed by Maria Lopez on Sep 2. Nothing above these limits happens without a new signature.</div></div>
          <Button variant="secondary" size="sm" iconLeft="pen-line" onClick={() => ctx.toast({ title: 'Draft ready', description: 'Change a limit, then sign to apply it.' })}>Change limits</Button>
        </div>
        <div>{d.tiers.map((t) => <TierRow key={t.tier} {...t} />)}</div>
      </section>
      <section className="kit-sec" style={{ gap: 16 }}>
        <h3 className="kc-section-title">This month</h3>
        <FactorBar label="Acted on its own" value={148} max={600} valueLabel="$148 of $600" hint="38 actions, all under $200" />
        <FactorBar label="Signed by you" value={3480} max={10000} valueLabel="$3,480" tone="teal" hint="6 approvals" />
        <FactorBar label="Blocked" value={1} max={10} valueLabel="1 payment" tone="danger" hint="Northside Packaging, $2,980" />
      </section>
      <section className="kit-sec" style={{ gap: 16 }}>
        <h3 className="kc-section-title">What KaChing did</h3>
        <ul className="kit-list">
          {d.recent.map((r, i) => <li key={i}><div><div className="kit-list__what">{r.what}</div><div className="kc-caption">{r.when}</div></div><StatusPill size="sm" status={r.status} /></li>)}
        </ul>
        <div><Button variant="ghost" size="sm" iconRight="arrow-right" onClick={() => ctx.trace('found')}>See an example trace</Button></div>
      </section>
    </div>
  );
}
Object.assign(window, { InboxView, InvoiceBody, FinancingView, TrustView });
