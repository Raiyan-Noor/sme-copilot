import React from 'react';

/** A figure the owner can click to see where it came from. Opens a trace drawer via onClick. */
export function FactNumber({ children, onClick, source, tone = 'default', className = '', ...rest }) {
  return (
    <button type="button" onClick={onClick} className={`kc-fact kc-fact--${tone} ${className}`}
      aria-label={source ? `${typeof children === 'string' ? children : ''}. Show trace: ${source}` : undefined}
      title={source ? `Source: ${source}` : 'Show where this number comes from'} {...rest}>
      {children}
    </button>
  );
}
