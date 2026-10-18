import React from 'react';
import { Icon } from '../icon/Icon.jsx';

/** Container. Maps to shadcn/ui Card. `improve` is the gold-outlined "one thing to improve" card. */
export function Card({ variant = 'default', eyebrow, title, description, action, footer, padding = 'md', children, className = '', ...rest }) {
  const eb = eyebrow === undefined && variant === 'improve' ? 'One thing to improve' : eyebrow;
  return (
    <section className={`kc-card kc-card--${variant} kc-card--pad-${padding} ${className}`} {...rest}>
      {eb || title || action ? (
        <header className="kc-card__head">
          <div className="kc-card__titles">
            {eb ? <div className="kc-card__eyebrow">{variant === 'improve' ? <Icon name="coins" size={16} /> : null}<span>{eb}</span></div> : null}
            {title ? <h3 className="kc-section-title">{title}</h3> : null}
            {description ? <p className="kc-card__desc">{description}</p> : null}
          </div>
          {action ? <div className="kc-card__action">{action}</div> : null}
        </header>
      ) : null}
      {children ? <div className="kc-card__body">{children}</div> : null}
      {footer ? <footer className="kc-card__foot">{footer}</footer> : null}
    </section>
  );
}
