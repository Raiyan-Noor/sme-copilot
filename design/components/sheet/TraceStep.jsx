import React from 'react';

/** One step in a trace: label, value, and source line. Use inside Sheet. */
export function TraceStep({ label, value, source, op, emphasis = false }) {
  return (
    <div className={`kc-trace${emphasis ? ' kc-trace--total' : ''}`}>
      <span className="kc-trace__op">{op || ''}</span>
      <div className="kc-trace__main">
        <div className="kc-trace__label">{label}</div>
        {source ? <div className="kc-trace__source">{source}</div> : null}
      </div>
      <span className="kc-trace__value">{value}</span>
    </div>
  );
}
