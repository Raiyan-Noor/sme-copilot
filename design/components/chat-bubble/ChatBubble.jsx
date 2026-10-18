import React from 'react';

/** Chat message. owner = the shop owner (right, raised bubble, sans), copilot = KaChing (left, unboxed serif). */
export function ChatBubble({ role = 'copilot', children, meta, name, avatarSrc, attachment, className = '' }) {
  const isOwner = role === 'owner';
  return (
    <div className={`kc-chat kc-chat--${role} ${className}`}>
      {!isOwner ? (
        <div className="kc-chat__avatar" aria-hidden="true">
          {avatarSrc ? <img src={avatarSrc} alt="" /> : <span>K</span>}
        </div>
      ) : null}
      <div className="kc-chat__col">
        {name ? <div className="kc-chat__name">{name}</div> : null}
        <div className="kc-chat__bubble">{children}</div>
        {attachment ? <div className="kc-chat__attach">{attachment}</div> : null}
        {meta ? <div className="kc-chat__meta">{meta}</div> : null}
      </div>
    </div>
  );
}
