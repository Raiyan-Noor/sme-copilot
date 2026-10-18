import React from 'react';
import { Icon } from '../icon/Icon.jsx';
import { FactNumber } from '../fact-number/FactNumber.jsx';

/** Big KPI figure with label and delta. Value becomes a FactNumber when onTrace is given. */
export function KpiTile({ label, value, delta, caption, icon, size = 'lg', onTrace, source, className = '' }) {
  const dTone = delta ? delta.tone || 'neutral' : null;
  const dIcon = dTone === 'good' ? 'trending-up' : dTone === 'bad' ? 'trending-down' : 'minus';
  return (
    <div className={`kc-kpi kc-kpi--${size} ${className}`}>
      <div className="kc-kpi__label">{icon ? <Icon name={icon} size={16} /> : null}<span>{label}</span></div>
      <div className="kc-kpi__value">{onTrace ? <FactNumber onClick={onTrace} source={source}>{value}</FactNumber> : value}</div>
      {delta || caption ? (
        <div className="kc-kpi__foot">
          {delta ? <span className={`kc-kpi__delta kc-kpi__delta--${dTone}`}><Icon name={dIcon} size={14} strokeWidth={2} />{delta.label}</span> : null}
          {caption ? <span className="kc-caption">{caption}</span> : null}
        </div>
      ) : null}
    </div>
  );
}
