import React from 'react';
import { Progress } from './Progress.jsx';

/** Labelled factor bar: why an offer fits, how much of a limit is used, risk factors. */
export function FactorBar({ label, value = 0, max = 100, valueLabel, hint, tone = 'brand', threshold, thresholdLabel, className = '' }) {
  const tp = threshold != null ? Math.max(0, Math.min(100, (threshold / max) * 100)) : null;
  return (
    <div className={`kc-factor ${className}`}>
      <div className="kc-factor__row">
        <span className="kc-factor__label">{label}</span>
        <span className="kc-factor__value">{valueLabel ?? value}</span>
      </div>
      <div className="kc-factor__track-wrap">
        <Progress value={value} max={max} tone={tone} size="sm" label={label} />
        {tp != null ? <span className="kc-factor__threshold" style={{ left: tp + '%' }} title={thresholdLabel}></span> : null}
      </div>
      {hint ? <div className="kc-caption">{hint}</div> : null}
    </div>
  );
}
