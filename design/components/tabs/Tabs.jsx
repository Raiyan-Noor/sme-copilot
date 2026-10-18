import React from 'react';

/** Underline tabs. Maps to shadcn/ui Tabs (value / defaultValue / onValueChange). */
export function Tabs({ items = [], value, defaultValue, onValueChange, size = 'md', className = '' }) {
  const [inner, setInner] = React.useState(defaultValue ?? (items[0] && items[0].value));
  const current = value ?? inner;
  const select = (v) => { if (value === undefined) setInner(v); onValueChange && onValueChange(v); };
  const onKey = (e, i) => {
    if (e.key !== 'ArrowRight' && e.key !== 'ArrowLeft') return;
    const n = (i + (e.key === 'ArrowRight' ? 1 : -1) + items.length) % items.length;
    select(items[n].value);
    const btns = e.currentTarget.parentElement.querySelectorAll('[role=tab]');
    btns[n] && btns[n].focus();
  };
  return (
    <div role="tablist" className={`kc-tabs kc-tabs--${size} ${className}`}>
      {items.map((t, i) => {
        const on = t.value === current;
        return (
          <button key={t.value} type="button" role="tab" aria-selected={on} tabIndex={on ? 0 : -1}
            className={`kc-tabs__tab${on ? ' is-active' : ''}`} onClick={() => select(t.value)} onKeyDown={(e) => onKey(e, i)}>
            <span>{t.label}</span>
            {t.count != null ? <span className="kc-tabs__count">{t.count}</span> : null}
          </button>
        );
      })}
    </div>
  );
}
