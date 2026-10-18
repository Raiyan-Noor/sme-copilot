import React from 'react';
import { Icon } from '../icon/Icon.jsx';

/** KaChing button. Maps to shadcn/ui Button. Labels are verb first, sentence case. */
export function Button({ variant = 'primary', size = 'md', iconLeft, iconRight, loading = false, disabled = false, fullWidth = false, type = 'button', className = '', children, ...rest }) {
  const iconSize = size === 'sm' ? 16 : 18;
  return (
    <button type={type} disabled={disabled || loading} aria-busy={loading || undefined}
      className={`kc-btn kc-btn--${variant} kc-btn--${size}${fullWidth ? ' kc-btn--full' : ''}${children == null || children === '' ? ' kc-btn--icon' : ''} ${className}`} {...rest}>
      {loading ? <Icon name="loader-circle" size={iconSize} className="kc-btn__spin" /> : iconLeft ? <Icon name={iconLeft} size={iconSize} /> : null}
      {children != null && children !== '' ? <span>{children}</span> : null}
      {iconRight && !loading ? <Icon name={iconRight} size={iconSize} /> : null}
    </button>
  );
}
