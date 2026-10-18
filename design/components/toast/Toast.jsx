import React from 'react';
import { Icon } from '../icon/Icon.jsx';

const ICONS = { default: 'info', success: 'circle-check', danger: 'ban', savings: 'coins' };

/** Transient confirmation. Maps to shadcn/ui Toast / Sonner. Position it yourself (bottom-right). */
export function Toast({ variant = 'default', title, description, action, onClose, icon, className = '' }) {
  return (
    <div role="status" aria-live="polite" className={`kc-toast kc-toast--${variant} ${className}`}>
      <span className="kc-toast__icon"><Icon name={icon || ICONS[variant]} size={20} /></span>
      <div className="kc-toast__content">
        {title ? <div className="kc-toast__title">{title}</div> : null}
        {description ? <div className="kc-toast__desc">{description}</div> : null}
      </div>
      {action ? <button type="button" className="kc-toast__action" onClick={action.onClick}>{action.label}</button> : null}
      {onClose ? <button type="button" className="kc-toast__close" aria-label="Close" onClick={onClose}><Icon name="x" size={16} /></button> : null}
    </div>
  );
}
