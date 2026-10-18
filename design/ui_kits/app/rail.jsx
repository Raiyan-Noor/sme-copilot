const RAIL_VIEWS = [
  { id: 'cash', label: 'Cash, next 30 days', icon: 'wallet' },
  { id: 'inbox', label: 'Inbox', icon: 'inbox', flagged: true },
  { id: 'financing', label: 'Financing', icon: 'landmark', meta: '2 fit' },
  { id: 'trust', label: 'Trust', icon: 'shield-check', meta: 'Signed Sep 2' },
];

function Rail({ ctx }) {
  const { KpiTile, Icon, StatusPill } = window.KaChingDesignSystem_2fdbe1;
  const d = window.KC_DATA;
  return (
    <aside className="kit-rail" aria-label="Today at a glance" data-screen-label="Rail">
      <div className="kit-rail__stats">
        <KpiTile size="md" label="Cash on hand" value="$18,240" delta={{ label: '+$1,120', tone: 'good' }} caption="vs last Friday" onTrace={() => ctx.trace('cash')} source="Bank feed, 2 accounts" />
        <KpiTile size="md" label="Safe to spend" value="$4,280" caption="through Oct 25" onTrace={() => ctx.trace('safe')} />
        <KpiTile size="md" label="Found this month" value="$340" caption="3 sources" onTrace={() => ctx.trace('found')} />
      </div>
      <nav className="kit-rail__nav" aria-label="Open a view">
        {RAIL_VIEWS.map((v) => (
          <button key={v.id} className="kit-railnav" onClick={() => ctx.open(v.id)}>
            <Icon name={v.icon} size={20} />
            <span>{v.label}</span>
            {v.flagged && ctx.fraudOpen ? <span className="kit-railnav__count" aria-label="1 flagged">1</span> : v.meta ? <span className="kit-railnav__meta">{v.meta}</span> : null}
          </button>
        ))}
      </nav>
      <div className="kit-rail__foot">
        <StatusPill status="synthetic" size="sm" />
        <div className="kit-shop">
          <span className="kit-shop__av">{d.owner.initials}</span>
          <div><div className="kit-shop__name">{d.owner.shop}</div><div className="kc-caption">Maria Lopez, owner</div></div>
        </div>
      </div>
    </aside>
  );
}
window.Rail = Rail;
