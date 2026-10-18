import React from 'react';
import { Icon } from '../icon/Icon.jsx';

const STATUS_MAP = {
  executed: { label: 'Executed', icon: 'circle-check', tone: 'success' },
  waiting: { label: 'Waiting for approval', icon: 'clock', tone: 'warning' },
  blocked: { label: 'Blocked', icon: 'ban', tone: 'danger' },
  fits: { label: 'Fits', icon: 'check', tone: 'success' },
  'doesnt-fit': { label: "Doesn't fit", icon: 'x', tone: 'neutral' },
  synthetic: { label: 'Synthetic data', icon: 'flask-conical', tone: 'synthetic' },
};

/** Status pill: always icon + word, never color alone. */
export function StatusPill({ status = 'waiting', label, size = 'md', className = '' }) {
  const s = STATUS_MAP[status] || STATUS_MAP.waiting;
  return (
    <span className={`kc-pill kc-pill--${s.tone} kc-pill--${size} ${className}`}>
      <Icon name={s.icon} size={size === 'sm' ? 12 : 14} strokeWidth={2} />
      <span>{label || s.label}</span>
    </span>
  );
}
