const KA_AV = 'assets/logo-mark.png';

function Ref({ icon, title, sub, onClick }) {
  const { Icon } = window.KaChingDesignSystem_2fdbe1;
  return (
    <button className="ka-ref" onClick={onClick}>
      <span className="ka-ref__icon"><Icon name={icon} size={20} /></span>
      <span className="ka-ref__txt"><div className="ka-ref__t">{title}</div>{sub ? <div className="kc-caption">{sub}</div> : null}</span>
      <span className="ka-ref__arrow"><Icon name="chevron-right" size={18} /></span>
    </button>
  );
}

const KA_REPLIES = {
  flour: (h) => ({ text: <>Yes. After payroll and rent you have {h.fact('$4,280', 'safe')} safe to spend through Oct 25. Forty bags from Fresh Farms is {h.fact('$1,080', 'ff')}, which leaves {h.fact('$3,200', 'left')}.</>,
    attachment: <Ref icon="wallet" title="Cash, next 30 days" sub="Forecast, buffer and three fixes" onClick={() => h.ctx.openPanel('cash')} /> }),
  split: (h) => ({ text: <>Done. I split it into two orders of 20 bags, Oct 17 and Oct 24, {h.fact('$540.00', 'ff')} each. Both are under your $2,000 limit, so each one waits for your signature the day before.</> }),
  thursday: (h) => ({ text: <>Payroll ({h.fact('$8,940', 'safe')}) lands Oct 24 and rent ({h.fact('$2,600', 'safe')}) the next day. Here's your cash for the next 30 days. You stay above your $1,000 buffer the whole time.</>,
    attachment: <Ref icon="wallet" title="Cash, next 30 days" sub={<>Lowest point $3,100 on Nov 11</>} onClick={() => h.ctx.openPanel('cash')} /> }),
  overnight: (h) => ({ text: <>I categorized 38 transactions, sent Oak St. Deli a reminder for {h.fact('$412.00', 'found')} and asked Square to refund a double fee. Each one is in the audit log.</>,
    attachment: <Ref icon="shield-check" title="Audit log" sub="Every action, hashed and anchored" onClick={() => h.ctx.openPanel('trust', { tab: 'audit' })} /> }),
  loans: (h) => ({ text: <>Three loans you qualify for. The cheapest is Main Street Credit Union: {h.fact('$518', 'safe')} a month for $25,000. I checked each one against your cash flow.</>,
    attachment: <Ref icon="landmark" title="Financing matches" sub="3 fit · 1 doesn't · Readiness Passport 5 of 6" onClick={() => h.ctx.openPanel('financing')} /> }),
  default: () => ({ text: <>I checked your accounts. I don't have enough to answer that yet. Which supplier or date do you mean?</> }),
};
const kaPick = (q) => /split|order it/i.test(q) ? 'split' : /flour|restock|afford/i.test(q) ? 'flour' : /thursday|tight/i.test(q) ? 'thursday' : /overnight|did you/i.test(q) ? 'overnight' : /loan|financ/i.test(q) ? 'loans' : 'default';

function Composer({ onSend, autoFocus }) {
  const { Button } = window.KaChingDesignSystem_2fdbe1;
  const [text, setText] = React.useState('');
  return (
    <form className="ka-compose" onSubmit={(e) => { e.preventDefault(); if (text.trim()) { onSend(text.trim()); setText(''); } }}>
      <input value={text} onChange={(e) => setText(e.target.value)} placeholder="Ask about your money" aria-label="Message" autoFocus={autoFocus} />
      <Button type="submit" size="sm" iconLeft="arrow-up" aria-label="Send" disabled={!text.trim()}></Button>
    </form>
  );
}

function Mandate({ ctx }) {
  const { Icon, StatusPill, Button } = window.KaChingDesignSystem_2fdbe1;
  return (
    <div className="ka-mandate">
      <div className="ka-mandate__top">
        <div className="ka-mandate__title"><Icon name="pen-line" size={18} style={{ color: 'var(--success)' }} />Payment mandate signed</div>
        <StatusPill status="executed" size="sm" />
      </div>
      <dl>
        <dt>Mandate ID</dt><dd className="ka-mandate__id">MND-2291-7F3A-C9E1</dd>
        <dt>Pays</dt><dd>$1,240.00 to Fresh Farms on Oct 21</dd>
        <dt>From</dt><dd>Checking ··4410</dd>
        <dt>Limit</dt><dd>Tier 2, within your $2,000 limit</dd>
        <dt>Signed</dt><dd>Maria Lopez, 9:16 am, passkey on this device</dd>
        <dt>Record</dt><dd>Anchored on Sepolia · 0x7f3a…c9e1</dd>
      </dl>
      <div className="ka-mandate__foot">
        <span className="kc-caption">You can revoke it until Oct 21, 9:00 am.</span>
        <Button variant="ghost" size="sm" iconRight="arrow-right" onClick={() => ctx.openPanel('trust', { tab: 'audit' })}>View in audit log</Button>
      </div>
    </div>
  );
}

function Resolved({ icon, tone, children }) {
  const { Icon } = window.KaChingDesignSystem_2fdbe1;
  return <div className="ka-resolved"><span className="i" style={{ color: tone }}><Icon name={icon} size={18} /></span><span>{children}</span></div>;
}

function Overnight() {
  const { Icon, StatusPill } = window.KaChingDesignSystem_2fdbe1;
  const [open, setOpen] = React.useState(false);
  return (
    <div>
      <button className={`ka-fold${open ? ' is-open' : ''}`} aria-expanded={open} onClick={() => setOpen((o) => !o)}>
        <span className="ok"><Icon name="circle-check" size={18} /></span>
        <span>I handled 3 things overnight</span>
        <span className="chev"><Icon name="chevron-right" size={16} /></span>
      </button>
      {open ? (
        <ul className="ka-foldlist">
          {window.KA.overnight.map((o) => <li key={o.what}><span className="w"><span>{o.what}</span><span className="kc-caption">{o.when}</span></span><StatusPill status="executed" size="sm" /></li>)}
        </ul>
      ) : null}
    </div>
  );
}

function Brief({ ctx, fact }) {
  const { ChatBubble, AlertBanner, ApprovalCard, Card, Badge, Button } = window.KaChingDesignSystem_2fdbe1;
  const a = window.KA.approval;
  const st = ctx.approval === 'signing' ? 'waiting' : ctx.approval;
  const attachment = (
    <div className="ka-attach">
      {ctx.fraudOpen ? (
        <AlertBanner className="ka-fraud" variant="fraud" title="Northside Packaging's bank details changed"
          actions={<><Button variant="destructive" size="sm" iconLeft="ban" onClick={ctx.blockFraud}>Keep payment blocked</Button><Button variant="secondary" size="sm" onClick={() => ctx.openPanel('email')}>Review invoice</Button></>}>
          Invoice #7710 asks for account ··8812. Their last 14 invoices used ··3307. I paused the $2,980.00 payment.
        </AlertBanner>
      ) : <Resolved icon="ban" tone="var(--danger)">Payment to Northside Packaging stays blocked. I emailed their known address to confirm.</Resolved>}
      <div id="ka-wait-approval">
        <ApprovalCard {...a} status={st} onAmountClick={() => ctx.trace(a.trace)}
          approveLabel={ctx.approval === 'signing' ? 'Signing…' : 'Sign and approve'}
          resolvedNote={st === 'executed' ? 'Signed by you at 9:16 am.' : 'Declined. Nothing was sent.'}
          onApprove={ctx.approve} onDecline={ctx.decline} />
      </div>
      {ctx.improve === 'waiting' ? (
        <div id="ka-wait-improve">
          <Card variant="improve" padding="md" title="Cancel two tools nobody uses" description="Canva and Loom cost $86 a month. Nobody on your team has logged in since June."
            action={<Badge variant="savings">Saves $86 a month</Badge>}
            footer={<div className="ka-improve-foot"><Button variant="secondary" size="sm" iconLeft="pen-line" onClick={ctx.signImprove}>Sign cancellation</Button><Button variant="ghost" size="sm" onClick={ctx.skipImprove}>Not now</Button></div>} />
        </div>
      ) : ctx.improve === 'executed'
        ? <Resolved icon="coins" tone="var(--success)">Cancellation signed. Canva and Loom end Nov 1. That saves $86 a month.</Resolved>
        : <Resolved icon="circle-slash" tone="var(--text-muted)">Kept Canva and Loom. I'll check again next month.</Resolved>}
      <Overnight />
    </div>
  );
  return (
    <ChatBubble role="copilot" name="Morning brief · Oct 18" meta="9:02 am" avatarSrc={KA_AV} attachment={attachment}>
      <span className="ka-p">Morning, Maria. Two things need your signature and one invoice looks wrong. Everything else is handled.</span>
      <span className="ka-p">Cash is steady at {fact('$18,240', 'cash')}. Through Oct 25 you can safely spend {fact('$4,280', 'safe')}.</span>
    </ChatBubble>
  );
}

function Conversation({ ctx, msgs, onSend, title }) {
  const { ChatBubble, FactNumber, Icon } = window.KaChingDesignSystem_2fdbe1;
  const d = window.KA;
  const fact = (v, key) => <FactNumber onClick={() => ctx.trace(key)}>{v}</FactNumber>;
  const h = { ctx, fact };
  const prev = React.useRef(msgs.length);
  React.useEffect(() => {
    const el = ctx.scrollerRef.current;
    if (el && msgs.length > prev.current) el.scrollTop = el.scrollHeight;
    prev.current = msgs.length;
  }, [msgs]);
  return (
    <>
      <div className="ka-scroll" ref={ctx.scrollerRef}>
        <div className="ka-col ka-msgs" role="log" aria-label={`Conversation: ${title}`}>
          {msgs.map((m, i) => {
            if (m.t === 'brief') return <Brief key={i} ctx={ctx} fact={fact} />;
            if (m.t === 'day') return <div key={i} className="ka-day">{m.text}</div>;
            if (m.t === 'note') return <div key={i} className="ka-note"><Icon name="repeat" size={14} />{m.text} · {m.meta}</div>;
            if (m.t === 'owner') return <ChatBubble key={i} role="owner" meta={m.meta}>{m.text}</ChatBubble>;
            if (m.t === 'thinking') return <ChatBubble key={i} role="copilot" avatarSrc={KA_AV}><span className="kc-caption">{m.text || 'Checking your accounts…'}</span></ChatBubble>;
            if (m.t === 'signed') return <ChatBubble key={i} role="copilot" meta={m.meta} avatarSrc={KA_AV} attachment={<Mandate ctx={ctx} />}>Signed. I'll pay Fresh Farms {fact('$1,240.00', 'ff')} on Oct 21 from ··4410 and keep the 2% discount.</ChatBubble>;
            if (m.t === 'reply') { const r = KA_REPLIES[m.key](h); return <ChatBubble key={i} role="copilot" meta={m.meta} avatarSrc={KA_AV} attachment={r.attachment}>{r.text}</ChatBubble>; }
            return null;
          })}
        </div>
      </div>
      <div className="ka-dock">
        <div className="ka-col">
          <div className="ka-sugg">{d.suggestions.map((s) => <button key={s} className="ka-chip" onClick={() => onSend(s)}>{s}</button>)}</div>
          <Composer onSend={onSend} />
          <div className="kc-caption ka-dock__note">KaChing acts only within the limits you signed.</div>
        </div>
      </div>
    </>
  );
}

function EmptyState({ onSend }) {
  const d = window.KA;
  return (
    <div className="ka-empty" data-screen-label="New conversation">
      <div className="ka-col" style={{ display: 'flex', flexDirection: 'column', gap: 28 }}>
        <div className="ka-greet"><img src={KA_AV} alt="" /><h1>Good evening, Maria</h1></div>
        <Composer onSend={onSend} autoFocus />
        <div className="ka-sugg">{d.emptySuggestions.map((s) => <button key={s} className="ka-chip" onClick={() => onSend(s)}>{s}</button>)}</div>
      </div>
    </div>
  );
}
Object.assign(window, { Conversation, EmptyState, kaPick, Ref });
