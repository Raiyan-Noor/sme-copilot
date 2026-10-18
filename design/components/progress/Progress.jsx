import React from 'react';

/** Plain progress bar. Maps to shadcn/ui Progress. */
export function Progress({ value = 0, max = 100, tone = 'brand', size = 'md', label, className = '' }) {
  const p = Math.max(0, Math.min(100, (Number(value) / max) * 100));
  return (
    <div className={`kc-progress kc-progress--${size} ${className}`} role="progressbar" aria-valuemin={0} aria-valuemax={max} aria-valuenow={value} aria-label={label}>
      <div className={`kc-progress__fill kc-progress__fill--${tone}`} style={{ width: p + '%' }}></div>
    </div>
  );
}
