function CashChart({ data }) {
  const W = 496, H = 200, P = { l: 40, r: 8, t: 20, b: 26 };
  const max = 20000, n = data.length;
  const x = (i) => P.l + (i / (n - 1)) * (W - P.l - P.r);
  const y = (v) => P.t + (1 - v / max) * (H - P.t - P.b);
  const line = data.map((v, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(' ');
  const low = data.reduce((m, v, i) => (v < data[m] ? i : m), 0);
  const t = { fontSize: 11, fill: 'var(--text-muted)', fontFamily: 'var(--font-body)' };
  return (
    <svg viewBox={`0 0 ${W} ${H}`} width="100%" style={{ display: 'block' }} role="img" aria-label="Cash forecast, next 30 days">
      {[0, 5000, 10000, 15000, 20000].map((v) => <g key={v}><line x1={P.l} x2={W - P.r} y1={y(v)} y2={y(v)} stroke="var(--border)" opacity="0.6" /><text x={P.l - 8} y={y(v) + 4} textAnchor="end" {...t}>${v / 1000}k</text></g>)}
      <line x1={P.l} x2={W - P.r} y1={y(1000)} y2={y(1000)} stroke="var(--chart-3)" strokeDasharray="4 5" strokeWidth="1.25" />
      <text x={P.l + 6} y={y(1000) - 6} {...t}>Your $1,000 buffer</text>
      <path d={`${line} L${x(n - 1)},${y(0)} L${x(0)},${y(0)} Z`} fill="var(--chart-1)" opacity="0.08" />
      <path d={line} fill="none" stroke="var(--chart-1)" strokeWidth="2" strokeLinejoin="round" />
      <circle cx={x(0)} cy={y(data[0])} r="4" fill="var(--chart-1)" />
      <circle cx={x(low)} cy={y(data[low])} r="4" fill="var(--surface-muted)" stroke="var(--chart-1)" strokeWidth="2" />
      <text x={x(low)} y={y(data[low]) - 10} textAnchor="middle" {...t} fontWeight="500" fill="var(--text)">Low $3,100</text>
      {['Oct 18', 'Oct 25', 'Nov 1', 'Nov 8', 'Nov 16'].map((l, i) => <text key={l} x={x(Math.round((i / 4) * (n - 1)))} y={H - 6} textAnchor={i === 0 ? 'start' : i === 4 ? 'end' : 'middle'} {...t}>{l}</text>)}
    </svg>
  );
}

function CashView({ ctx }) {
  const { Table, StatusPill, KpiTile, Button } = window.KaChingDesignSystem_2fdbe1;
  const d = window.KA;
  return (
    <div className="ka-stack" style={{ gap: 40 }}>
      <section className="ka-sec" style={{ gap: 24 }}>
        <p className="ka-advise">Here's your cash for the next 30 days. Payroll and rent land the same week, and you stay above your buffer.</p>
        <div className="ka-kpis2">
          <KpiTile size="md" label="Lowest point, Nov 11" value="$3,100" caption="$2,100 above buffer" onTrace={() => ctx.trace('low')} />
          <KpiTile size="md" label="Safe to spend" value="$4,280" caption="through Oct 25" onTrace={() => ctx.trace('safe')} />
        </div>
        <CashChart data={d.forecast} />
      </section>
      <section className="ka-sec">
        <div className="ka-sechead"><h3 className="kc-section-title">Ways to raise the low point</h3><span className="kc-caption">Ranked by effect</span></div>
        <ol className="ka-fixes">
          {d.fixes.map((f, i) => (
            <li key={f.title}>
              <span className="n">{i + 1}</span><span className="t">{f.title}</span><span className="g">{f.gain}</span>
              <span className="w">{f.why}</span>
              <span className="a"><Button variant={i === 0 ? 'secondary' : 'ghost'} size="sm" onClick={() => i === 2 ? ctx.goToWaiting('ka-wait-improve') : ctx.toast({ title: i === 0 ? 'Reminder prepared' : 'Change prepared', description: 'It needs your signature in chat.' })}>{f.action}</Button></span>
            </li>
          ))}
        </ol>
      </section>
      <section className="ka-sec">
        <div className="ka-sechead"><h3 className="kc-section-title">Coming up</h3><span className="kc-caption">Next 7 days</span></div>
        <Table rowKey="id" density="compact" columns={[
          { key: 'date', header: 'Date', width: 64 },
          { key: 'what', header: 'What', render: (r) => <div><div style={{ fontWeight: 500 }}>{r.what}</div><div className="kc-caption">{r.kind}</div></div> },
          { key: 'status', header: 'Status', render: (r) => <StatusPill size="sm" status={r.status} label={r.status === 'executed' ? 'Scheduled' : undefined} /> },
          { key: 'amount', header: 'Amount', align: 'right', render: (r) => <span style={{ color: r.amount.startsWith('+') ? 'var(--success)' : 'var(--text)' }}>{r.amount}</span> },
        ]} rows={d.upcoming} />
      </section>
    </div>
  );
}

function Offer({ o, ctx, defaultOpen }) {
  const { StatusPill, Button, Icon } = window.KaChingDesignSystem_2fdbe1;
  const [open, setOpen] = React.useState(defaultOpen);
  const pass = o.rules.filter((r) => r[2]).length;
  return (
    <div className="ka-offer">
      <div className="ka-offer__top">
        <div><div className="kc-caption">{o.product}</div><div className="kc-section-title">{o.lender}</div></div>
        <StatusPill status={o.fit} size="sm" />
      </div>
      <dl className="ka-terms">
        <div><dt>Amount</dt><dd className="big">{o.amount}</dd></div>
        <div><dt>APR</dt><dd>{o.apr}</dd></div>
        <div><dt>Monthly</dt><dd>{o.monthly}</dd></div>
        <div><dt>Term</dt><dd>{o.term}</dd></div>
      </dl>
      <div>
        <button className="ka-fold" style={{ marginLeft: -12 }} aria-expanded={open} onClick={() => setOpen((x) => !x)}>
          <span>{pass} of {o.rules.length} rules pass</span><span className="chev" style={{ transform: open ? 'rotate(90deg)' : 'none' }}><Icon name="chevron-right" size={16} /></span>
        </button>
        {open ? o.rules.map(([l, v, ok]) => (
          <div className="ka-rule" key={l}><span className="ka-rule__l">{l}</span><span className="ka-rule__r"><span className="ka-rule__v">{v}</span><StatusPill size="sm" status={ok ? 'fits' : 'doesnt-fit'} label={ok ? 'Pass' : 'Fail'} /></span></div>
        )) : null}
      </div>
      <div>{o.fit === 'fits'
        ? <Button variant="secondary" size="sm" iconLeft="file-text" onClick={() => ctx.toast({ title: 'Application drafted', description: `${o.lender}. You review and send it yourself.` })}>Prepare application</Button>
        : <Button variant="ghost" size="sm" onClick={() => ctx.toast({ title: 'Noted', description: 'I will not show QuickFund again.' })}>Hide this offer</Button>}</div>
    </div>
  );
}

function FinancingView({ ctx }) {
  const { Progress, Icon, Button, StatusPill } = window.KaChingDesignSystem_2fdbe1;
  const d = window.KA;
  const ready = d.passport.filter((p) => p.ok).length;
  return (
    <div className="ka-stack">
      <p className="ka-advise">Three loans you qualify for. I compare offers; I never apply. Taking on debt is set to Never in your limits.</p>
      <section className="ka-passport" aria-label="Readiness Passport">
        <div className="ka-passport__top">
          <div><div className="kc-section-title">Readiness Passport</div><div className="kc-caption">What lenders ask for, kept up to date</div></div>
          <span className="kc-label" style={{ fontVariantNumeric: 'tabular-nums' }}>{ready} of {d.passport.length} ready</span>
        </div>
        <Progress value={ready} max={d.passport.length} />
        <div className="ka-passlist">
          {d.passport.map((p) => (
            <div className="ka-check" key={p.label}>
              <Icon name={p.ok ? 'circle-check' : 'clock'} size={16} style={{ color: p.ok ? 'var(--success)' : 'var(--warning)' }} />
              <div><div>{p.label}</div><div className="kc-caption">{p.source}</div></div>
            </div>
          ))}
        </div>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          <Button variant="secondary" size="sm" iconLeft="camera" onClick={() => ctx.toast({ title: 'Upload link sent', description: 'Check your phone to add your ID.' })}>Add owner ID</Button>
          <Button variant="ghost" size="sm" iconLeft="share" onClick={() => ctx.toast({ title: 'Passport link copied', description: 'Expires in 7 days.' })}>Share passport</Button>
        </div>
      </section>
      <section>{d.offers.map((o, i) => <Offer key={o.id} o={o} ctx={ctx} defaultOpen={i === 0} />)}</section>
    </div>
  );
}

function InboxView({ ctx }) {
  const { Table, StatusPill } = window.KaChingDesignSystem_2fdbe1;
  const d = window.KA;
  return (
    <div className="ka-stack">
      <Table rowKey="id" onRowClick={(r) => r.id === 'i2' ? ctx.pushPanel('email') : r.id === 'i1' ? ctx.trace('ff') : ctx.toast({ title: `${r.vendor} ${r.inv}`, description: r.check })} columns={[
        { key: 'vendor', header: 'Supplier', render: (r) => <div><div style={{ fontWeight: 500 }}>{r.vendor} <span className="kc-caption">{r.inv}</span></div><div className="kc-caption" style={{ color: r.status === 'blocked' && ctx.fraudOpen ? 'var(--danger)' : undefined }}>{r.check}</div></div> },
        { key: 'status', header: 'Status', render: (r) => <StatusPill size="sm" status={r.status} label={r.label} /> },
        { key: 'amount', header: 'Amount', align: 'right' },
      ]} rows={d.invoices} />
      <div className="kc-caption">Every invoice is checked against the supplier's history before it can be paid.</div>
    </div>
  );
}

function EmailView({ ctx }) {
  const { Icon } = window.KaChingDesignSystem_2fdbe1;
  const F = ({ n, children }) => <span className="ka-flag">{children}<sup>{n}</sup></span>;
  return (
    <div className="ka-stack">
      <div className="ka-email">
        <section className="ka-sec">
          <div className="kc-label" style={{ color: 'var(--text-muted)', fontWeight: 400 }}>Original email</div>
          <article className="ka-mail">
            <dl className="ka-mail__hdr">
              <dt>From</dt><dd>Northside Billing &lt;<F n="1">billing@northside-packing.co</F>&gt;</dd>
              <dt>To</dt><dd>maria@lopezbakery.com</dd>
              <dt>Date</dt><dd>Oct 16, 3:38 pm</dd>
              <dt>Subject</dt><dd>Updated bank details, invoice #7710</dd>
            </dl>
            <p>Hi Maria,</p>
            <p>We have moved our business banking. Please send payment for invoice #7710 ($2,980.00) to our <F n="2">new account ending 8812</F>, routing 121000358.</p>
            <p><F n="3">Please process this today to avoid a late fee.</F> Our old account is closed, so payments sent there will bounce.</p>
            <p><F n="4">Reply to this email only. Our office phones are down this week.</F></p>
            <p>Thanks,<br />Dana, Accounts</p>
          </article>
        </section>
        <section className="ka-sec" style={{ gap: 16 }}>
          <div className="kc-label" style={{ color: 'var(--danger)', fontWeight: 500, display: 'flex', alignItems: 'center', gap: 6 }}><Icon name="shield-alert" size={16} />4 red flags</div>
          <ol className="ka-flags">
            <li><span className="n">1</span><span className="t">Lookalike domain</span><span className="d">northside-packing.co. Their real invoices come from northsidepackaging.com, 23 times since 2023.</span></li>
            <li><span className="n">2</span><span className="t">New bank account</span><span className="d">··8812. Their last 14 invoices used ··3307.</span></li>
            <li><span className="n">3</span><span className="t">Pressure to pay today</span><span className="d">Northside has never charged you a late fee. Their terms are net 30.</span></li>
            <li><span className="n">4</span><span className="t">Asks you not to call</span><span className="d">Scammers block the one check that catches them.</span></li>
          </ol>
        </section>
      </div>
      <section className="ka-sec" style={{ gap: 16 }}>
        <h3 className="kc-section-title">Check with a phone call</h3>
        <div className="ka-callnum">
          <Icon name="phone" size={20} style={{ color: 'var(--brand-primary)' }} />
          <div style={{ flex: 1 }}><div className="num">(503) 555-0142</div><div className="kc-caption">Northside's number from your records since 2023. Not from this email.</div></div>
        </div>
        <ol className="ka-script">
          <li><span>"Hi, this is Maria from Lopez Bakery. I got an email asking us to pay invoice #7710 into a new account."</span></li>
          <li><span>"Did you change your bank details this month?"</span></li>
          <li><span>"Which account should we pay? Just the last four digits."</span><span></span></li>
        </ol>
        <p className="ka-text" style={{ color: 'var(--text-muted)' }}>If they say ··3307 or don't know about the email, it's fraud. I'll keep the payment blocked and pay the old account once you confirm.</p>
      </section>
    </div>
  );
}

function TrustView({ ctx, tab, setTab }) {
  const { Tabs, TierRow, Button, FactorBar, StatusPill, Table, Icon, KpiTile } = window.KaChingDesignSystem_2fdbe1;
  const d = window.KA;
  const [verify, setVerify] = React.useState('idle');
  const rows = ctx.approval === 'executed'
    ? [{ id: 'l1', when: 'Oct 18, 9:16 am', what: 'Signed mandate MND-2291-7F3A-C9E1', who: 'Signed by you', hash: '0x7f3a…c9e1', status: 'executed', amount: '$1,240.00' }, ...d.audit] : d.audit;
  return (
    <div className="ka-stack" style={{ gap: 24 }}>
      <Tabs value={tab} onValueChange={setTab} items={[{ value: 'limits', label: 'Limits and tiers' }, { value: 'audit', label: 'Audit log' }, { value: 'redteam', label: 'Red-team' }]} />
      {tab === 'limits' ? (
        <div className="ka-stack">
          <section className="ka-sec" style={{ gap: 4 }}>
            <div className="ka-sechead"><span className="kc-caption">Signed by Maria Lopez on Sep 2. Nothing above these limits happens without a new signature.</span>
              <Button variant="secondary" size="sm" iconLeft="pen-line" onClick={() => ctx.toast({ title: 'Draft ready', description: 'Change a limit, then sign to apply it.' })}>Change limits</Button></div>
            <div>{d.tiers.map((t) => <TierRow key={t.tier} {...t} />)}</div>
          </section>
          <section className="ka-sec" style={{ gap: 16 }}>
            <h3 className="kc-section-title">This month</h3>
            <FactorBar label="Acted on its own" value={148} max={600} valueLabel="$148 of $600" hint="38 actions, all under $200" />
            <FactorBar label="Signed by you" value={3480} max={10000} valueLabel="$3,480" tone="teal" hint="6 approvals" />
          </section>
        </div>
      ) : null}
      {tab === 'audit' ? (
        <div className="ka-stack" style={{ gap: 20 }}>
          <div className="ka-sechead" style={{ alignItems: 'center' }}>
            <span className="kc-caption">Each record is hashed and linked to the one before. The chain is anchored on Sepolia every 6 hours.</span>
            <Button variant="secondary" size="sm" iconLeft="link" loading={verify === 'running'} onClick={() => { setVerify('running'); setTimeout(() => setVerify('done'), 1200); }}>Verify chain</Button>
          </div>
          {verify === 'done' ? (
            <div className="ka-verify" role="status">
              <div className="ka-vrow"><span className="i"><Icon name="circle-check" size={18} /></span><div><div className="t">Chain intact</div><div className="kc-caption">{rows.length + 209} records. Every hash links to the one before.</div></div></div>
              <div className="ka-vrow"><span className="i"><Icon name="circle-check" size={18} /></span><div><div className="t">On-chain match</div><div className="kc-caption">Sepolia block 6,912,404 · root 0x7f3a…c9e1 matches your log, anchored Oct 18, 6:00 am</div></div></div>
            </div>
          ) : null}
          <Table rowKey="id" density="compact" columns={[
            { key: 'what', header: 'What', render: (r) => <div><div style={{ fontWeight: 500 }}>{r.what}</div><div className="kc-caption">{r.when} · {r.who} · {r.hash}</div></div> },
            { key: 'status', header: 'Status', render: (r) => <StatusPill size="sm" status={r.status} /> },
            { key: 'amount', header: 'Amount', align: 'right' },
          ]} rows={rows} />
        </div>
      ) : null}
      {tab === 'redteam' ? (
        <div className="ka-stack" style={{ gap: 20 }}>
          <div className="ka-kpis2">
            <KpiTile size="md" label="Attacks stopped" value="24 of 24" caption="last run Oct 14" />
            <KpiTile size="md" label="Next run" value="Oct 21" caption="every Monday, 3:00 am" />
          </div>
          <p className="ka-text" style={{ color: 'var(--text-muted)' }}>Every week an independent test tries to trick KaChing into paying, moving or borrowing money it shouldn't.</p>
          <ul className="ka-rt">
            {d.redteam.map((r) => <li key={r.what}><div><div style={{ fontSize: 14, fontWeight: 500 }}>{r.what}</div><div className="kc-caption">{r.how} · {r.result}</div></div><StatusPill size="sm" status="executed" label="Stopped" /></li>)}
          </ul>
        </div>
      ) : null}
    </div>
  );
}

function TraceView({ k }) {
  const { TraceStep } = window.KaChingDesignSystem_2fdbe1;
  const t = window.KA.traces[k];
  const total = t.steps[t.steps.length - 1];
  return (
    <div className="ka-stack" style={{ gap: 20 }}>
      <div className="ka-trace-sum"><span className="kc-label" style={{ color: 'var(--text-muted)', fontWeight: 400 }}>{t.title}</span><span className="kc-display-number">{total.value}</span><span className="kc-caption">{t.asOf}</span></div>
      <div>{t.steps.map((s, i) => <TraceStep key={i} {...s} />)}</div>
      <div className="kc-caption">Every figure links back to a bank feed, a document or a setting you chose.</div>
    </div>
  );
}

const KA_PANELS = {
  cash: { title: 'Cash, next 30 days', desc: 'From your bank feed, payroll schedule and open invoices' },
  financing: { title: 'Financing', desc: '3 fit · 1 doesn\'t fit' },
  inbox: { title: 'Inbox', desc: '4 invoices this week' },
  email: { title: 'This email is suspicious', desc: 'Northside Packaging · invoice #7710 · $2,980.00', wide: true },
  trust: { title: 'Limits and trust', desc: 'What KaChing may do, and proof of what it did' },
  trace: { title: 'Where this number comes from' },
};

function DetailPanel({ ctx, stack }) {
  const { Button, Icon } = window.KaChingDesignSystem_2fdbe1;
  const top = stack[stack.length - 1];
  const [shown, setShown] = React.useState(top);
  const body = React.useRef(null);
  React.useEffect(() => { if (top) setShown(top); }, [top]);
  React.useEffect(() => { if (body.current) body.current.scrollTop = 0; }, [shown && shown.view, shown && shown.key]);
  const v = shown && shown.view;
  const m = v ? KA_PANELS[v] : {};
  let content = null, foot = null;
  if (v === 'cash') content = <CashView ctx={ctx} />;
  if (v === 'financing') content = <FinancingView ctx={ctx} />;
  if (v === 'inbox') content = <InboxView ctx={ctx} />;
  if (v === 'trust') content = <TrustView ctx={ctx} tab={shown.tab || 'limits'} setTab={(t) => ctx.setPanelTab(t)} />;
  if (v === 'trace') {
    content = <TraceView k={shown.key} />;
    foot = <><Button variant="secondary" size="sm" iconLeft="download" onClick={() => ctx.toast({ title: 'Trace exported', description: 'Saved as CSV.' })}>Export trace</Button><Button variant="ghost" size="sm" iconLeft="message-square" onClick={() => { ctx.ask(`Explain ${window.KA.traces[shown.key].title.toLowerCase()}`); }}>Ask about this number</Button></>;
  }
  if (v === 'email') {
    content = <EmailView ctx={ctx} />;
    foot = ctx.fraudOpen
      ? <><Button variant="destructive" size="sm" iconLeft="ban" onClick={() => { ctx.blockFraud(); ctx.closePanel(); }}>Keep payment blocked</Button><Button variant="ghost" size="sm" iconLeft="copy" onClick={() => ctx.toast({ title: 'Call script copied' })}>Copy call script</Button></>
      : <span className="kc-caption" style={{ display: 'flex', alignItems: 'center', gap: 8 }}><Icon name="ban" size={16} style={{ color: 'var(--danger)' }} />Payment stays blocked. I emailed their known address.</span>;
  }
  const open = !!top;
  return (
    <aside className={`ka-panel${open ? ' is-open' : ''}`} style={{ '--panel-w': m.wide ? '760px' : '560px' }} aria-label={m.title} aria-hidden={!open} data-screen-label={`Panel: ${m.title || 'closed'}`}>
      <header className={`ka-panel__head${stack.length > 1 ? ' has-back' : ''}`}>
        {stack.length > 1 ? <button className="ka-ibtn" aria-label="Back" onClick={ctx.popPanel}><Icon name="arrow-left" size={20} /></button> : null}
        <div className="ka-panel__titles"><h2 className="kc-page-title">{m.title}</h2>{m.desc ? <div className="kc-caption">{m.desc}</div> : null}</div>
        <button className="ka-ibtn" aria-label="Close panel" onClick={ctx.closePanel}><Icon name="x" size={20} /></button>
      </header>
      <div className="ka-panel__body" ref={body}>{content}</div>
      {foot ? <footer className="ka-panel__foot">{foot}</footer> : null}
    </aside>
  );
}
Object.assign(window, { DetailPanel, KA_PANELS });
