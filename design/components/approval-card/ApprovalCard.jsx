import React from 'react';
import { Icon } from '../icon/Icon.jsx';
import { Button } from '../button/Button.jsx';
import { StatusPill } from '../badge/StatusPill.jsx';
import { FactNumber } from '../fact-number/FactNumber.jsx';

/** An action the copilot prepared that needs the owner's signature. */
export function ApprovalCard({ title, amount, onAmountClick, description, facts = [], limitNote, status = 'waiting', meta, resolvedNote,
  approveLabel = 'Sign and approve', declineLabel = 'Decline', onApprove, onDecline, className = '' }) {
  const pending = status === 'waiting';
  return (
    <article className={`kc-approval kc-approval--${status} ${className}`}>
      <div className="kc-approval__top">
        <StatusPill status={status} />
        {meta ? <span className="kc-caption">{meta}</span> : null}
      </div>
      <div className="kc-approval__main">
        <div className="kc-approval__titles">
          <h3 className="kc-section-title">{title}</h3>
          {description ? <p className="kc-approval__desc">{description}</p> : null}
        </div>
        {amount ? <div className="kc-approval__amount">{onAmountClick ? <FactNumber onClick={onAmountClick}>{amount}</FactNumber> : amount}</div> : null}
      </div>
      {facts.length ? (
        <dl className="kc-approval__facts">
          {facts.map((f, i) => (<div key={i} className="kc-approval__fact"><dt>{f.label}</dt><dd>{f.value}</dd></div>))}
        </dl>
      ) : null}
      {limitNote ? <div className="kc-approval__limit"><Icon name="shield-check" size={16} /><span>{limitNote}</span></div> : null}
      {pending ? (
        <div className="kc-approval__actions">
          <Button variant="primary" iconLeft="pen-line" onClick={onApprove}>{approveLabel}</Button>
          <Button variant="secondary" onClick={onDecline}>{declineLabel}</Button>
        </div>
      ) : resolvedNote ? <div className="kc-approval__resolved kc-caption">{resolvedNote}</div> : null}
    </article>
  );
}
