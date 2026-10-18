import React from 'react';
import { Icon } from '../icon/Icon.jsx';

/** Side drawer. Maps to shadcn/ui Sheet. Used as the trace drawer behind FactNumber. */
export function Sheet({ open, onOpenChange, title, description, children, footer, side = 'right', width = 440, contained = false, className = '' }) {
  React.useEffect(() => {
    if (!open) return;
    const onKey = (e) => { if (e.key === 'Escape') onOpenChange && onOpenChange(false); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, onOpenChange]);
  if (!open) return null;
  return (
    <div className={`kc-sheet${contained ? ' kc-sheet--contained' : ''} ${className}`}>
      <div className="kc-sheet__scrim" onClick={() => onOpenChange && onOpenChange(false)}></div>
      <aside role="dialog" aria-modal="true" aria-label={typeof title === 'string' ? title : undefined}
        className={`kc-sheet__panel kc-sheet__panel--${side}`} style={{ width }}>
        <header className="kc-sheet__head">
          <div className="kc-sheet__titles">
            {title ? <h2 className="kc-section-title">{title}</h2> : null}
            {description ? <p className="kc-sheet__desc">{description}</p> : null}
          </div>
          <button type="button" className="kc-sheet__close" aria-label="Close" onClick={() => onOpenChange && onOpenChange(false)}><Icon name="x" size={20} /></button>
        </header>
        <div className="kc-sheet__body">{children}</div>
        {footer ? <footer className="kc-sheet__foot">{footer}</footer> : null}
      </aside>
    </div>
  );
}
