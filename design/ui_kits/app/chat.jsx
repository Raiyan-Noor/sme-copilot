const CHAT_REPLIES = {
  flour: (h) => ({ text: <>Yes. After payroll and rent you have {h.fact('$4,280', 'safe')} safe to spend. 40 bags from Fresh Farms is $1,080. Want me to prepare the order?</> }),
  thursday: (h) => ({ text: <>Payroll ($8,940) lands Oct 24 and rent ($2,600) the day after. Cash drops to about {h.fact('$4,660', 'safe')}. Still above your buffer.</>,
    attachment: <div className="kit-actions"><h.Button variant="secondary" size="sm" iconLeft="wallet" onClick={() => h.ctx.open('cash')}>Open cash, next 30 days</h.Button></div> }),
  week: (h) => ({ text: <>I categorized 38 transactions, sent one reminder, paid City Power, and blocked one payment that looked like fraud.</>,
    attachment: <div className="kit-actions"><h.Button variant="secondary" size="sm" iconLeft="shield-check" onClick={() => h.ctx.open('trust')}>Open trust</h.Button></div> }),
  default: () => ({ text: <>I checked your accounts. I don't have enough to answer that yet. Can you tell me which supplier or date you mean?</> }),
};
const chatPick = (q) => /flour|restock|afford/i.test(q) ? 'flour' : /thursday|tight/i.test(q) ? 'thursday' : /week|did you/i.test(q) ? 'week' : 'default';

function Conversation({ ctx, seed, onSeedUsed }) {
  const { ChatBubble, Button, FactNumber, AlertBanner, ApprovalCard, Badge } = window.KaChingDesignSystem_2fdbe1;
  const d = window.KC_DATA;
  const AV = '../../assets/logo-mark.png';
  const [msgs, setMsgs] = React.useState([{ brief: 'lead' }, { brief: 'cash' }, { brief: 'tools' }]);
  const [text, setText] = React.useState('');
  const [thinking, setThinking] = React.useState(false);
  const [toolsPrepared, setToolsPrepared] = React.useState(false);
  const scroller = React.useRef(null);
  const fact = (v, key) => <FactNumber onClick={() => ctx.trace(key)}>{v}</FactNumber>;
  const h = { ctx, fact, Button };
  const now = () => new Date().toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' }).toLowerCase();
  const send = (q) => {
    const body = (q ?? text).trim(); if (!body) return;
    setMsgs((m) => [...m, { role: 'owner', text: body, meta: now() }]); setText(''); setThinking(true);
    setTimeout(() => { setThinking(false); setMsgs((m) => [...m, { role: 'copilot', meta: now(), reply: chatPick(body) }]); }, 700);
  };
  React.useEffect(() => { if (seed) { send(seed); onSeedUsed(); } }, [seed]);
  React.useEffect(() => { const el = scroller.current; if (el && msgs.length > 3) el.scrollTop = el.scrollHeight; }, [msgs, thinking]);

  const briefs = {
    lead: () => ({
      name: 'Morning brief · Friday, Oct 18', meta: '9:02 am',
      text: 'Morning, Maria. One invoice looks wrong, so I paused it. Two payments need your signature. Everything else is handled.',
      attachment: (
        <div className="kit-attach">
          {ctx.fraudOpen ? (
            <AlertBanner variant="fraud" title="Northside Packaging's bank details changed"
              actions={<><Button variant="destructive" size="sm" iconLeft="ban" onClick={ctx.blockFraud}>Keep payment blocked</Button><Button variant="secondary" size="sm" onClick={() => ctx.openInvoice('i2')}>Review invoice</Button></>}>
              Invoice #7710 asks for account ··8812. Their last 14 invoices used ··3307. I paused the $2,980.00 payment until you check with them.
            </AlertBanner>
          ) : null}
          {d.approvals.map((a) => {
            const st = ctx.approvalState[a.id] || 'waiting';
            return (
              <ApprovalCard key={a.id} {...a} status={st} onAmountClick={a.trace ? () => ctx.trace(a.trace) : undefined}
                approveLabel={a.id === 'a2' ? 'Send reminder' : 'Sign and approve'}
                resolvedNote={st === 'executed' ? 'Signed by you just now.' : 'Declined. Nothing was sent.'}
                onApprove={() => ctx.approve(a)} onDecline={() => ctx.decline(a)} />
            );
          })}
        </div>
      ),
    }),
    cash: () => ({
      text: <>Cash stays above your $1,000 buffer all month. The low point is $3,100 on Nov 11, after payroll and rent. Through Oct 25 you can spend {fact('$4,280', 'safe')}.</>,
      attachment: <div className="kit-actions"><Button variant="secondary" size="sm" iconLeft="wallet" onClick={() => ctx.open('cash')}>Open cash, next 30 days</Button></div>,
    }),
    tools: () => ({
      text: toolsPrepared ? 'The cancellation for Canva and Loom is ready. Sign it in Trust or tell me here.' : 'You pay $86 a month for Canva and Loom. Nobody on your team has opened either since June. Want me to prepare the cancellation?',
      attachment: toolsPrepared ? null : (
        <div className="kit-actions">
          <Button variant="secondary" size="sm" iconLeft="circle-slash" onClick={() => { setToolsPrepared(true); ctx.toast({ variant: 'savings', title: 'Cancellation prepared', description: 'Saves $86 a month once you sign.' }); }}>Prepare cancellation</Button>
          <Badge variant="savings">Saves $86 a month</Badge>
        </div>
      ),
    }),
  };

  return (
    <>
      <div className="kit-scroll" ref={scroller}>
        <div className="kit-col kit-msgs" role="log" aria-label="Conversation with KaChing">
          {msgs.map((m, i) => {
            if (m.brief) { const b = briefs[m.brief](); return <ChatBubble key={i} role="copilot" name={b.name} meta={b.meta} attachment={b.attachment} avatarSrc={AV}>{b.text}</ChatBubble>; }
            if (m.reply) { const r = CHAT_REPLIES[m.reply](h); return <ChatBubble key={i} role="copilot" meta={m.meta} attachment={r.attachment} avatarSrc={AV}>{r.text}</ChatBubble>; }
            return <ChatBubble key={i} role="owner" meta={m.meta}>{m.text}</ChatBubble>;
          })}
          {thinking ? <ChatBubble role="copilot" avatarSrc={AV}><span className="kc-caption">Checking your accounts…</span></ChatBubble> : null}
        </div>
      </div>
      <div className="kit-dock">
        <div className="kit-col">
          <div className="kit-sugg">{d.suggestions.map((s) => <button key={s} className="kit-chip" onClick={() => send(s)}>{s}</button>)}</div>
          <form className="kit-compose" onSubmit={(e) => { e.preventDefault(); send(); }}>
            <input value={text} onChange={(e) => setText(e.target.value)} placeholder="Ask about your money" aria-label="Message" />
            <Button type="submit" size="sm" iconLeft="arrow-up" aria-label="Send" disabled={!text.trim()}></Button>
          </form>
          <div className="kc-caption kit-dock__note">KaChing acts only within the limits you signed.</div>
        </div>
      </div>
    </>
  );
}
window.Conversation = Conversation;
