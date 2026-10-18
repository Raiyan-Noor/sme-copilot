import React from 'react';

const LUCIDE_SRC = 'https://unpkg.com/lucide@0.460.0/dist/umd/lucide.min.js';
let lucideLoading = null;
function ensureLucide() {
  if (typeof window === 'undefined') return Promise.resolve();
  if (window.lucide && window.lucide.icons) return Promise.resolve();
  if (!lucideLoading) {
    lucideLoading = new Promise((resolve) => {
      const s = document.createElement('script');
      s.src = LUCIDE_SRC; s.onload = resolve; s.onerror = resolve;
      document.head.appendChild(s);
    });
  }
  return lucideLoading;
}
const toPascal = (n) => String(n).split(/[-_ ]/).map((p) => p.charAt(0).toUpperCase() + p.slice(1)).join('');

/** Lucide icon at the KaChing default 1.5px stroke. Loads Lucide from CDN on first use. */
export function Icon({ name, size = 20, strokeWidth = 1.5, color = 'currentColor', title, className, style }) {
  const [, force] = React.useState(0);
  React.useEffect(() => {
    if (!(window.lucide && window.lucide.icons)) ensureLucide().then(() => force((x) => x + 1));
  }, []);
  const icons = typeof window !== 'undefined' && window.lucide && window.lucide.icons;
  const node = icons && (icons[toPascal(name)] || icons[name]);
  let children = [];
  if (node) children = node[0] === 'svg' ? node[2] || [] : node;
  return (
    <svg xmlns="http://www.w3.org/2000/svg" width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color}
      strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round" className={className}
      style={{ flexShrink: 0, display: 'inline-block', verticalAlign: 'middle', ...style }}
      aria-hidden={title ? undefined : true} role={title ? 'img' : undefined}>
      {title ? <title>{title}</title> : null}
      {children.map(([tag, attrs], i) => {
        const { key, ...rest } = attrs || {};
        return React.createElement(tag, { key: i, ...rest });
      })}
    </svg>
  );
}
