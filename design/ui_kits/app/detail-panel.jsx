const DETAIL_META = {
  cash: { title: 'Cash, next 30 days', desc: 'Forecast from your bank feed, payroll schedule and open invoices' },
  inbox: { title: 'Inbox', desc: 'Every invoice is checked before it is paid' },
  financing: { title: 'Financing', desc: 'Offers matched to your cash flow' },
  trust: { title: 'Trust', desc: 'What KaChing may do on its own, and what it did' },
};

function CashChart({ data }) {
  const W = 496, H = 200, P = { l: 40, r: 8, t: 20, b: 26 };
  const max = 20000, n = data.length;
  const x = (i) => P.l + (i / (n - 1)) * (W - P.l - P.r);
  const y = (v) => P.t + (1 - v / max) * (H - P.t - P.b);
  const line = data.map((v, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(' ');
  const area = `${line} L${x(n - 1)},${y(0)} L${x(0)},${y(0)} Z`;
  const low = data.reduce((m, v, i) => (v < data[m] ? i : m), 0);
  const t = { fontSize: 11, fill: 'var(--text-muted)', fontFamily: 'var(--font-body)' };
  return (
    <svg viewBox={`0 0 ${W} ${H}`} width="100%" style={{ display: 'block' }} role="img" aria-label="Cash forecast, next 30 days">
      {[0, 5000, 10000, 15000, 20000].map((v) => (
        <g key={v}><line x1={P.l} x2={W - P.r} y1={y(v)} y2={y(v)} stroke="var(--border)" opacity="0.6" /><text x={P.l - 8} y={y(v) + 4} textAnchor="end" {...t}>${v / 1000}k</text></g>
      ))}
      <line x1={P.l} x2={W - P.r} y1={y(1000)} y2={y(1000)} stroke="var(--chart-3)" strokeDasharray="4 5" strokeWidth="1.25" />
      <text x={P.l + 6} y={y(1000) - 6} {...t}>Your $1,000 buffer</text>
      <path d={area} fill="var(--chart-1)" opacity="0.08" />
      <path d={line} fill="none" stroke="var(--chart-1)" strokeWidth="2" strokeLinejoin="round" />
      <circle cx={x(0)} cy={y(data[0])} r="4" fill="var(--chart-1)" />
      <circle cx={x(low)} cy={y(data[low])} r="4" fill="var(--surface-muted)" stroke="var(--chart-1)" strokeWidth="2" />
      <text x={x(low)} y={y(data[low]) - 10} textAnchor="middle" {...t} fontWeight="500" fill="var(--text)">Low: ${data[low].toLocaleString()}</text>
      {['Oct 18', 'Oct 25', 'Nov 1', 'Nov 8', 'Nov 16'].map((l, i) => (
        <text key={l} x={x(Math.round((i / 4) * (n - 1)))} y={H - 6} textAnchor={i === 0 ? 'start' : i === 4 ? 'end' : 'middle'} {...t}>{l}</text>
      ))}
    </svg>
  );
}

function CashView({ ctx }) {
  const { Table, StatusPill, KpiTile, FactNumber } = window.KaChingDesignSystem_2fdbe1;
  const d = window.KC_DATA;
  return (
    <div className="kit-stack" style={{ gap: 40 }}>
      <section className="kit-sec" style={{ gap: 24 }}>
        <div className="kit-kpis2">
          <KpiTile size="md" label="Lowest point, Nov 11" value="$3,100" delta={{ label: 'Above your buffer', tone: 'good' }} />
          <KpiTile size="md" label="Safe to spend" value="$4,280" caption="through Oct 25" onTrace={() => ctx.trace('safe')} />
        </div>
        <CashChart data={d.forecast} />
        <p className="kit-p" style={{ color: 'var(--text-muted)' }}>Thursday is tight because payroll and rent land the same week. You stay above your buffer. If Hillside Café pays on time you'll have <FactNumber onClick={() => ctx.trace('safe')}>$640</FactNumber> more.</p>
      </section>
      <section className="kit-sec">
        <div className="kit-sechead"><h3 className="kc-section-title">Coming up</h3><span className="kc-caption">Next 10 days</span></div>
        <Table rowKey="id" columns={[
          { key: 'date', header: 'Date', width: 72 },
          { key: 'what', header: 'What', render: (r) => <div><div style={{ fontWeight: 500 }}>{r.what}</div><div className="kc-caption">{r.kind}</div></div> },
          { key: 'status', header: 'Status', render: (r) => <StatusPill size="sm" status={r.status} label={r.status === 'executed' ? 'Scheduled' : undefined} /> },
          { key: 'amount', header: 'Amount', align: 'right', render: (r) => <span style={{ color: r.amount.startsWith('+') ? 'var(--success)' : 'var(--text)' }}>{r.amount}</span> },
        ]} rows={d.upcoming} />
      </section>
    </div>
  );
}

function DetailPanel({ ctx, view }) {
  const { Button } = window.KaChingDesignSystem_2fdbe1;
  const [shown, setShown] = React.useState(view);
  const body = React.useRef(null);
  const inv = ctx.invoice;
  React.useEffect(() => { if (view) setShown(view); }, [view]);
  React.useEffect(() => { if (body.current) body.current.scrollTop = 0; }, [shown, inv]);
  const m = shown ? DETAIL_META[shown] : null;
  let title = m && m.title, desc = m && m.desc, content = null, foot = null;
  if (shown === 'cash') content = <CashView ctx={ctx} />;
  if (shown === 'financing') content = <FinancingView ctx={ctx} />;
  if (shown === 'trust') content = <TrustView ctx={ctx} />;
  const onInvoice = shown === 'inbox' && inv;
  if (shown === 'inbox') {
    if (inv) {
      title = `${inv.vendor} ${inv.inv}`; desc = 'Invoice details and checks';
      content = <InvoiceBody inv={inv} />;
      foot = inv.status === 'blocked'
        ? <><Button variant="destructive" size="sm" iconLeft="ban" onClick={() => { ctx.setInvoice(null); ctx.blockFraud(); }}>Keep blocked</Button><Button variant="secondary" size="sm" onClick={() => ctx.toast({ title: 'Call scheduled', description: 'Reminder set for 10:00 am.' })}>Call supplier first</Button></>
        : inv.status === 'waiting' ? <Button size="sm" iconLeft="pen-line" onClick={() => { ctx.setInvoice(null); inv.id === 'i1' ? ctx.approve(window.KC_DATA.approvals[0]) : ctx.toast({ variant: 'success', title: 'Payment scheduled', description: `${inv.amount} to ${inv.vendor}` }); }}>Sign and approve</Button> : null;
    } else content = <InboxView ctx={ctx} />;
  }
  return (
    <aside className="kit-detail" aria-label={title} aria-hidden={!view} data-screen-label={`Detail: ${title || 'closed'}`}>
      <header className="kit-detail__head">
        {onInvoice ? <Button variant="ghost" size="sm" iconLeft="arrow-left" aria-label="Back to inbox" onClick={() => ctx.setInvoice(null)}></Button> : null}
        <div className="kit-detail__titles">
          <h2 className="kc-page-title">{title}</h2>
          {desc ? <div className="kc-caption">{desc}</div> : null}
        </div>
        <Button variant="ghost" size="sm" iconLeft="x" aria-label="Close panel" onClick={ctx.close}></Button>
      </header>
      <div className="kit-detail__body" ref={body}>{content}</div>
      {foot ? <footer className="kit-detail__foot">{foot}</footer> : null}
    </aside>
  );
}
Object.assign(window, { DetailPanel, CashChart });
