import React from 'react';
import { Icon } from '../icon/Icon.jsx';

/** Small label. Maps to shadcn/ui Badge. `savings` is green: money found or saved. */
export function Badge({ variant = 'neutral', icon, children, className = '' }) {
  const ic = icon === undefined && variant === 'savings' ? 'coins' : icon;
  return (
    <span className={`kc-badge kc-badge--${variant} ${className}`}>
      {ic ? <Icon name={ic} size={14} /> : null}
      <span>{children}</span>
    </span>
  );
}
