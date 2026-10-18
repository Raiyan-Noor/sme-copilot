import React from 'react';
import { Icon } from '../icon/Icon.jsx';
import { Button } from '../button/Button.jsx';

const MODES = {
  auto: { label: 'Acts on its own', icon: 'zap' },
  approval: { label: 'Asks first', icon: 'pen-line' },
  never: { label: 'Never', icon: 'ban' },
};

/** One permission tier the owner has signed: what the copilot may do, up to what amount, with which tools. */
export function TierRow({ tier, name, description, mode = 'approval', limit, tools = [], signedNote, onEdit, editLabel = 'Change limit', className = '' }) {
  const m = MODES[mode] || MODES.approval;
  return (
    <div className={`kc-tier kc-tier--${mode} ${className}`}>
      <div className="kc-tier__num" aria-label={`Tier ${tier}`}>{tier}</div>
      <div className="kc-tier__main">
        <div className="kc-tier__head">
          <span className="kc-tier__name">{name}</span>
          <span className={`kc-tier__mode kc-tier__mode--${mode}`}><Icon name={m.icon} size={14} strokeWidth={2} />{m.label}</span>
        </div>
        {description ? <p className="kc-tier__desc">{description}</p> : null}
        {tools.length ? (
          <ul className="kc-tier__tools" aria-label="Tools">
            {tools.map((t, i) => {
              const tool = typeof t === 'string' ? { label: t } : t;
              return <li key={i} className="kc-tier__tool">{tool.icon ? <Icon name={tool.icon} size={14} /> : null}{tool.label}</li>;
            })}
          </ul>
        ) : null}
        {signedNote ? <div className="kc-caption kc-tier__signed"><Icon name="signature" size={14} />{signedNote}</div> : null}
      </div>
      <div className="kc-tier__side">
        {limit ? <div className="kc-tier__limit"><span className="kc-caption">Limit</span><span className="kc-tier__limit-val">{limit}</span></div> : null}
        {onEdit ? <Button variant="ghost" size="sm" onClick={onEdit}>{editLabel}</Button> : null}
      </div>
    </div>
  );
}
