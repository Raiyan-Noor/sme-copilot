function Sparkline({ data, w = 252, h = 64 }) {
  const max = 20000, n = data.length;
  const x = (i) => (i / (n - 1)) * w;
  const y = (v) => 4 + (1 - v / max) * (h - 8);
  const line = data.map((v, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(' ');
  const low = data.reduce((m, v, i) => (v < data[m] ? i : m), 0);
  return (
    <svg viewBox={`0 0 ${w} ${h}`} width="100%" height={h} style={{ display: 'block', overflow: 'visible' }} role="img" aria-label="Cash, next 30 days. Stays above your $1,000 buffer.">
      <line x1="0" x2={w} y1={y(1000)} y2={y(1000)} stroke="var(--chart-3)" strokeDasharray="4 5" strokeWidth="1.25" />
      <path d={`${line} L${w},${h} L0,${h} Z`} fill="var(--chart-1)" opacity="0.06" />
      <path d={line} fill="none" stroke="var(--chart-1)" strokeWidth="1.5" strokeLinejoin="round" />
      <circle cx={x(0)} cy={y(data[0])} r="3" fill="var(--chart-1)" />
      <circle cx={x(low)} cy={y(data[low])} r="3" fill="var(--surface)" stroke="var(--chart-1)" strokeWidth="1.5" />
    </svg>
  );
}

function Sidebar({ ctx, mini, drawer }) {
  const { Button, Icon, StatusPill } = window.KaChingDesignSystem_2fdbe1;
  const d = window.KA;
  const [menu, setMenu] = React.useState(false);
  const links = [
    { id: 'inbox', label: 'Inbox', icon: 'inbox', count: ctx.fraudOpen ? 1 : 0 },
    { id: 'financing', label: 'Financing', icon: 'landmark' },
    { id: 'trust', label: 'Limits and trust', icon: 'shield-check' },
  ];
  const go = (fn) => () => { fn(); ctx.closeDrawer(); };
  return (
    <nav className={`ka-sb${mini ? ' is-mini' : ''}${drawer ? ' is-drawer' : ''}`} aria-label="Conversations and views" data-screen-label="Sidebar">
      <div className="ka-sb__top">
        {mini ? <img className="ka-sb__mark" src="assets/logo-mark.png" alt="KaChing" /> : <img src="assets/logo-wordmark-dark.png" alt="KaChing" />}
        {ctx.phone
          ? <button className="ka-ibtn" aria-label="Close menu" onClick={ctx.closeDrawer}><Icon name="x" size={20} /></button>
          : <button className="ka-ibtn" aria-label={mini ? 'Expand sidebar' : 'Collapse sidebar'} title={mini ? 'Expand' : 'Collapse'} onClick={ctx.toggleSb}><Icon name={mini ? 'panel-left-open' : 'panel-left-close'} size={20} /></button>}
      </div>
      <div className="ka-sb__new">
        {mini
          ? <button className="ka-ibtn" style={{ background: 'var(--surface-raised)', color: 'var(--text)' }} aria-label="New conversation" title="New conversation" onClick={go(ctx.newConv)}><Icon name="plus" size={20} /></button>
          : <Button variant="secondary" size="md" iconLeft="plus" fullWidth onClick={go(ctx.newConv)}>New conversation</Button>}
      </div>
      {mini ? null : (
        <div className="ka-sb__group">
          <div className="ka-sb__label">Conversations</div>
          {ctx.convList.map((c) => (
            <button key={c.id} className={`ka-nav${ctx.conv === c.id ? ' is-active' : ''}`} onClick={go(() => ctx.setConv(c.id))} aria-current={ctx.conv === c.id ? 'page' : undefined}>
              <span className="t">{c.title}</span>
            </button>
          ))}
        </div>
      )}
      <div className="ka-sb__foot">
        {links.map((l) => (
          <button key={l.id} className="ka-nav" title={mini ? l.label : undefined} aria-label={mini ? l.label : undefined} onClick={go(() => ctx.openPanel(l.id))}>
            <Icon name={l.icon} size={18} />
            {mini ? (l.count ? <span className="ka-nav__dot" aria-hidden="true"></span> : null) : <span className="t">{l.label}</span>}
            {!mini && l.count ? <span className="ka-nav__count" aria-label={`${l.count} flagged`}>{l.count} flagged</span> : null}
          </button>
        ))}
        <div className="ka-sb__sep"></div>
        {menu && !mini ? (
          <div className="ka-menu" role="menu">
            <button className="ka-nav" role="menuitem" onClick={() => setMenu(false)}><Icon name="check" size={16} style={{ color: 'var(--brand-primary)' }} /><span className="t">Lopez Bakery</span></button>
            <button className="ka-nav" role="menuitem" onClick={() => { setMenu(false); ctx.toast({ title: 'Business setup started', description: 'Connect a bank account to begin.' }); }}><Icon name="plus" size={16} /><span className="t">Add a business</span></button>
          </div>
        ) : null}
        <button className="ka-shop" aria-label="Switch business" aria-expanded={menu} onClick={() => (mini ? ctx.toggleSb() : setMenu((m) => !m))}>
          <span className="ka-shop__av">{d.owner.initials}</span>
          {mini ? null : <><span className="ka-shop__txt"><div className="ka-shop__name">{d.owner.shop}</div><div className="kc-caption">{d.owner.pack}</div></span><Icon name="chevrons-up-down" size={16} style={{ color: 'var(--text-muted)' }} /></>}
        </button>
        {mini ? null : <div className="ka-synth"><StatusPill status="synthetic" size="sm" /></div>}
      </div>
    </nav>
  );
}

function RailBody({ ctx }) {
  const { KpiTile, Icon } = window.KaChingDesignSystem_2fdbe1;
  const d = window.KA;
  const w = ctx.waiting;
  return (
    <>
      <div className="ka-rail__stats">
        <KpiTile size="md" label="Cash on hand" value="$18,240" delta={{ label: '+$1,120', tone: 'good' }} caption="vs last week" onTrace={() => ctx.trace('cash')} />
        <KpiTile size="md" label="Safe to spend" value="$4,280" caption="through Oct 25" onTrace={() => ctx.trace('safe')} />
        <KpiTile size="md" label="Runway" value="74 days" caption="if no money came in" onTrace={() => ctx.trace('runway')} />
        <KpiTile size="md" label="Found this month" value="$340" caption="3 sources" onTrace={() => ctx.trace('found')} />
      </div>
      <div className="ka-rail__sec">
        <button className="ka-spark" onClick={() => ctx.openPanel('cash')} aria-label="Open cash, next 30 days">
          <div className="ka-spark__row"><span className="kc-label" style={{ color: 'var(--text-muted)', fontWeight: 400 }}>Cash, next 30 days</span><Icon name="arrow-up-right" size={16} style={{ color: 'var(--text-muted)' }} /></div>
          <Sparkline data={d.forecast} />
          <div className="ka-spark__row"><span className="kc-caption">Low $3,100 on Nov 11</span><span className="kc-caption">Buffer $1,000</span></div>
        </button>
      </div>
      <div className="ka-rail__sec">
        <button className={`ka-waiting${w ? '' : ' is-zero'}`} onClick={ctx.scrollToWaiting}>
          <Icon name={w ? 'clock' : 'circle-check'} size={18} />
          <span>{w ? 'Waiting for you' : 'Nothing waiting'}</span>
          <span className="n">{w}</span>
        </button>
      </div>
      <div className="ka-rail__foot">
        <button className="ka-anchor" onClick={() => ctx.openPanel('trust', { tab: 'audit' })}>
          <span className="ok"><Icon name="circle-check" size={14} /></span>
          <span>Records anchored · Sepolia</span>
          <span style={{ marginLeft: 'auto' }}>6:00 am</span>
        </button>
      </div>
    </>
  );
}

function Rail({ ctx, hidden }) {
  const { Icon } = window.KaChingDesignSystem_2fdbe1;
  return (
    <aside className={`ka-rail${hidden ? ' is-hidden' : ''}`} aria-label="Today at a glance" aria-hidden={hidden} data-screen-label="Stats rail">
      <div className="ka-rail__head">
        <span className="kc-label" style={{ color: 'var(--text-muted)', fontWeight: 400 }}>Today, Oct 18</span>
        <button className="ka-ibtn" aria-label="Hide stats" title="Hide stats" onClick={() => ctx.setRailOpen(false)} style={{ marginRight: -8 }}><Icon name="panel-right-close" size={20} /></button>
      </div>
      <RailBody ctx={ctx} />
    </aside>
  );
}

function TodaySheet({ ctx, open }) {
  const { Icon } = window.KaChingDesignSystem_2fdbe1;
  return (
    <div className={`ka-todaysheet${open ? ' is-open' : ''}`} role="dialog" aria-label="Today" aria-hidden={!open} data-screen-label="Phone: Today">
      <div className="ka-panel__head">
        <div className="ka-panel__titles"><h2 className="kc-page-title">Today</h2><div className="kc-caption">Oct 18 · Lopez Bakery</div></div>
        <button className="ka-ibtn" aria-label="Close" onClick={() => ctx.setToday(false)}><Icon name="x" size={20} /></button>
      </div>
      <div className="ka-rail"><RailBody ctx={ctx} /></div>
    </div>
  );
}
Object.assign(window, { Sidebar, Rail, TodaySheet, Sparkline });
