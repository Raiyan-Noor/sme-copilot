import React from 'react';
import { Icon } from '../icon/Icon.jsx';

const ICONS = { fraud: 'shield-alert', info: 'info' };
const WORDS = { fraud: 'Possible fraud', info: 'Note' };

/** Full-width banner. Maps to shadcn/ui Alert. fraud is red and reserved for suspected fraud. */
export function AlertBanner({ variant = 'info', title, children, actions, onDismiss, eyebrow, className = '' }) {
  const eb = eyebrow === undefined ? WORDS[variant] : eyebrow;
  return (
    <div role={variant === 'fraud' ? 'alert' : 'status'} className={`kc-alert kc-alert--${variant} ${className}`}>
      <span className="kc-alert__icon"><Icon name={ICONS[variant] || 'info'} size={20} /></span>
      <div className="kc-alert__content">
        {eb ? <div className="kc-alert__eyebrow">{eb}</div> : null}
        {title ? <div className="kc-alert__title">{title}</div> : null}
        {children ? <div className="kc-alert__body">{children}</div> : null}
        {actions ? <div className="kc-alert__actions">{actions}</div> : null}
      </div>
      {onDismiss ? <button type="button" className="kc-alert__close" onClick={onDismiss} aria-label="Dismiss"><Icon name="x" size={18} /></button> : null}
    </div>
  );
}
