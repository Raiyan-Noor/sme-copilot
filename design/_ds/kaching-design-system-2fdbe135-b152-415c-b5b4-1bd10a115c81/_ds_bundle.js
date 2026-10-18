/* @ds-bundle: {"format":4,"namespace":"KaChingDesignSystem_2fdbe1","components":[{"name":"AlertBanner","sourcePath":"components/alert-banner/AlertBanner.jsx"},{"name":"ApprovalCard","sourcePath":"components/approval-card/ApprovalCard.jsx"},{"name":"Badge","sourcePath":"components/badge/Badge.jsx"},{"name":"StatusPill","sourcePath":"components/badge/StatusPill.jsx"},{"name":"Button","sourcePath":"components/button/Button.jsx"},{"name":"Card","sourcePath":"components/card/Card.jsx"},{"name":"ChatBubble","sourcePath":"components/chat-bubble/ChatBubble.jsx"},{"name":"FactNumber","sourcePath":"components/fact-number/FactNumber.jsx"},{"name":"Icon","sourcePath":"components/icon/Icon.jsx"},{"name":"KpiTile","sourcePath":"components/kpi-tile/KpiTile.jsx"},{"name":"FactorBar","sourcePath":"components/progress/FactorBar.jsx"},{"name":"Progress","sourcePath":"components/progress/Progress.jsx"},{"name":"Sheet","sourcePath":"components/sheet/Sheet.jsx"},{"name":"TraceStep","sourcePath":"components/sheet/TraceStep.jsx"},{"name":"Table","sourcePath":"components/table/Table.jsx"},{"name":"Tabs","sourcePath":"components/tabs/Tabs.jsx"},{"name":"TierRow","sourcePath":"components/tier-row/TierRow.jsx"},{"name":"Toast","sourcePath":"components/toast/Toast.jsx"}],"sourceHashes":{"components/alert-banner/AlertBanner.jsx":"63b90ed49682","components/approval-card/ApprovalCard.jsx":"328112687027","components/badge/Badge.jsx":"32181e62cdf7","components/badge/StatusPill.jsx":"4791004f70f4","components/button/Button.jsx":"601a9e30748e","components/card/Card.jsx":"026bf3b250f8","components/chat-bubble/ChatBubble.jsx":"4c98de47360c","components/fact-number/FactNumber.jsx":"8977e4599e12","components/icon/Icon.jsx":"ed2410bd3878","components/kpi-tile/KpiTile.jsx":"0ae84146fb92","components/progress/FactorBar.jsx":"3075a50bb4c8","components/progress/Progress.jsx":"512c94886e3e","components/sheet/Sheet.jsx":"9c8fea53e282","components/sheet/TraceStep.jsx":"f0a1f53fa27d","components/table/Table.jsx":"1333f982f5e7","components/tabs/Tabs.jsx":"3370fe2540a1","components/tier-row/TierRow.jsx":"5f59e9bf1684","components/toast/Toast.jsx":"cbac2c1c08a1","ui_kits/app/chat.jsx":"a6cff915341e","ui_kits/app/data.js":"dba61c672d01","ui_kits/app/detail-panel.jsx":"d6a1c63ddda6","ui_kits/app/detail-views.jsx":"91f36a8630e7","ui_kits/app/rail.jsx":"260b88f1c9d1"},"inlinedExternals":[],"unexposedExports":[]} */

(() => {

const __ds_ns = (window.KaChingDesignSystem_2fdbe1 = window.KaChingDesignSystem_2fdbe1 || {});

const __ds_scope = {};

(__ds_ns.__errors = __ds_ns.__errors || []);

// components/chat-bubble/ChatBubble.jsx
try { (() => {
/** Chat message. owner = the shop owner (right, raised bubble, sans), copilot = KaChing (left, unboxed serif). */
function ChatBubble({
  role = 'copilot',
  children,
  meta,
  name,
  avatarSrc,
  attachment,
  className = ''
}) {
  const isOwner = role === 'owner';
  return /*#__PURE__*/React.createElement("div", {
    className: `kc-chat kc-chat--${role} ${className}`
  }, !isOwner ? /*#__PURE__*/React.createElement("div", {
    className: "kc-chat__avatar",
    "aria-hidden": "true"
  }, avatarSrc ? /*#__PURE__*/React.createElement("img", {
    src: avatarSrc,
    alt: ""
  }) : /*#__PURE__*/React.createElement("span", null, "K")) : null, /*#__PURE__*/React.createElement("div", {
    className: "kc-chat__col"
  }, name ? /*#__PURE__*/React.createElement("div", {
    className: "kc-chat__name"
  }, name) : null, /*#__PURE__*/React.createElement("div", {
    className: "kc-chat__bubble"
  }, children), attachment ? /*#__PURE__*/React.createElement("div", {
    className: "kc-chat__attach"
  }, attachment) : null, meta ? /*#__PURE__*/React.createElement("div", {
    className: "kc-chat__meta"
  }, meta) : null));
}
Object.assign(__ds_scope, { ChatBubble });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/chat-bubble/ChatBubble.jsx", error: String((e && e.message) || e) }); }

// components/fact-number/FactNumber.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
/** A figure the owner can click to see where it came from. Opens a trace drawer via onClick. */
function FactNumber({
  children,
  onClick,
  source,
  tone = 'default',
  className = '',
  ...rest
}) {
  return /*#__PURE__*/React.createElement("button", _extends({
    type: "button",
    onClick: onClick,
    className: `kc-fact kc-fact--${tone} ${className}`,
    "aria-label": source ? `${typeof children === 'string' ? children : ''}. Show trace: ${source}` : undefined,
    title: source ? `Source: ${source}` : 'Show where this number comes from'
  }, rest), children);
}
Object.assign(__ds_scope, { FactNumber });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/fact-number/FactNumber.jsx", error: String((e && e.message) || e) }); }

// components/icon/Icon.jsx
try { (() => {
const LUCIDE_SRC = 'https://unpkg.com/lucide@0.460.0/dist/umd/lucide.min.js';
let lucideLoading = null;
function ensureLucide() {
  if (typeof window === 'undefined') return Promise.resolve();
  if (window.lucide && window.lucide.icons) return Promise.resolve();
  if (!lucideLoading) {
    lucideLoading = new Promise(resolve => {
      const s = document.createElement('script');
      s.src = LUCIDE_SRC;
      s.onload = resolve;
      s.onerror = resolve;
      document.head.appendChild(s);
    });
  }
  return lucideLoading;
}
const toPascal = n => String(n).split(/[-_ ]/).map(p => p.charAt(0).toUpperCase() + p.slice(1)).join('');

/** Lucide icon at the KaChing default 1.5px stroke. Loads Lucide from CDN on first use. */
function Icon({
  name,
  size = 20,
  strokeWidth = 1.5,
  color = 'currentColor',
  title,
  className,
  style
}) {
  const [, force] = React.useState(0);
  React.useEffect(() => {
    if (!(window.lucide && window.lucide.icons)) ensureLucide().then(() => force(x => x + 1));
  }, []);
  const icons = typeof window !== 'undefined' && window.lucide && window.lucide.icons;
  const node = icons && (icons[toPascal(name)] || icons[name]);
  let children = [];
  if (node) children = node[0] === 'svg' ? node[2] || [] : node;
  return /*#__PURE__*/React.createElement("svg", {
    xmlns: "http://www.w3.org/2000/svg",
    width: size,
    height: size,
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: color,
    strokeWidth: strokeWidth,
    strokeLinecap: "round",
    strokeLinejoin: "round",
    className: className,
    style: {
      flexShrink: 0,
      display: 'inline-block',
      verticalAlign: 'middle',
      ...style
    },
    "aria-hidden": title ? undefined : true,
    role: title ? 'img' : undefined
  }, title ? /*#__PURE__*/React.createElement("title", null, title) : null, children.map(([tag, attrs], i) => {
    const {
      key,
      ...rest
    } = attrs || {};
    return React.createElement(tag, {
      key: i,
      ...rest
    });
  }));
}
Object.assign(__ds_scope, { Icon });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/icon/Icon.jsx", error: String((e && e.message) || e) }); }

// components/alert-banner/AlertBanner.jsx
try { (() => {
const ICONS = {
  fraud: 'shield-alert',
  info: 'info'
};
const WORDS = {
  fraud: 'Possible fraud',
  info: 'Note'
};

/** Full-width banner. Maps to shadcn/ui Alert. fraud is red and reserved for suspected fraud. */
function AlertBanner({
  variant = 'info',
  title,
  children,
  actions,
  onDismiss,
  eyebrow,
  className = ''
}) {
  const eb = eyebrow === undefined ? WORDS[variant] : eyebrow;
  return /*#__PURE__*/React.createElement("div", {
    role: variant === 'fraud' ? 'alert' : 'status',
    className: `kc-alert kc-alert--${variant} ${className}`
  }, /*#__PURE__*/React.createElement("span", {
    className: "kc-alert__icon"
  }, /*#__PURE__*/React.createElement(__ds_scope.Icon, {
    name: ICONS[variant] || 'info',
    size: 20
  })), /*#__PURE__*/React.createElement("div", {
    className: "kc-alert__content"
  }, eb ? /*#__PURE__*/React.createElement("div", {
    className: "kc-alert__eyebrow"
  }, eb) : null, title ? /*#__PURE__*/React.createElement("div", {
    className: "kc-alert__title"
  }, title) : null, children ? /*#__PURE__*/React.createElement("div", {
    className: "kc-alert__body"
  }, children) : null, actions ? /*#__PURE__*/React.createElement("div", {
    className: "kc-alert__actions"
  }, actions) : null), onDismiss ? /*#__PURE__*/React.createElement("button", {
    type: "button",
    className: "kc-alert__close",
    onClick: onDismiss,
    "aria-label": "Dismiss"
  }, /*#__PURE__*/React.createElement(__ds_scope.Icon, {
    name: "x",
    size: 18
  })) : null);
}
Object.assign(__ds_scope, { AlertBanner });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/alert-banner/AlertBanner.jsx", error: String((e && e.message) || e) }); }

// components/badge/Badge.jsx
try { (() => {
/** Small label. Maps to shadcn/ui Badge. `savings` is green: money found or saved. */
function Badge({
  variant = 'neutral',
  icon,
  children,
  className = ''
}) {
  const ic = icon === undefined && variant === 'savings' ? 'coins' : icon;
  return /*#__PURE__*/React.createElement("span", {
    className: `kc-badge kc-badge--${variant} ${className}`
  }, ic ? /*#__PURE__*/React.createElement(__ds_scope.Icon, {
    name: ic,
    size: 14
  }) : null, /*#__PURE__*/React.createElement("span", null, children));
}
Object.assign(__ds_scope, { Badge });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/badge/Badge.jsx", error: String((e && e.message) || e) }); }

// components/badge/StatusPill.jsx
try { (() => {
const STATUS_MAP = {
  executed: {
    label: 'Executed',
    icon: 'circle-check',
    tone: 'success'
  },
  waiting: {
    label: 'Waiting for approval',
    icon: 'clock',
    tone: 'warning'
  },
  blocked: {
    label: 'Blocked',
    icon: 'ban',
    tone: 'danger'
  },
  fits: {
    label: 'Fits',
    icon: 'check',
    tone: 'success'
  },
  'doesnt-fit': {
    label: "Doesn't fit",
    icon: 'x',
    tone: 'neutral'
  },
  synthetic: {
    label: 'Synthetic data',
    icon: 'flask-conical',
    tone: 'synthetic'
  }
};

/** Status pill: always icon + word, never color alone. */
function StatusPill({
  status = 'waiting',
  label,
  size = 'md',
  className = ''
}) {
  const s = STATUS_MAP[status] || STATUS_MAP.waiting;
  return /*#__PURE__*/React.createElement("span", {
    className: `kc-pill kc-pill--${s.tone} kc-pill--${size} ${className}`
  }, /*#__PURE__*/React.createElement(__ds_scope.Icon, {
    name: s.icon,
    size: size === 'sm' ? 12 : 14,
    strokeWidth: 2
  }), /*#__PURE__*/React.createElement("span", null, label || s.label));
}
Object.assign(__ds_scope, { StatusPill });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/badge/StatusPill.jsx", error: String((e && e.message) || e) }); }

// components/button/Button.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
/** KaChing button. Maps to shadcn/ui Button. Labels are verb first, sentence case. */
function Button({
  variant = 'primary',
  size = 'md',
  iconLeft,
  iconRight,
  loading = false,
  disabled = false,
  fullWidth = false,
  type = 'button',
  className = '',
  children,
  ...rest
}) {
  const iconSize = size === 'sm' ? 16 : 18;
  return /*#__PURE__*/React.createElement("button", _extends({
    type: type,
    disabled: disabled || loading,
    "aria-busy": loading || undefined,
    className: `kc-btn kc-btn--${variant} kc-btn--${size}${fullWidth ? ' kc-btn--full' : ''}${children == null || children === '' ? ' kc-btn--icon' : ''} ${className}`
  }, rest), loading ? /*#__PURE__*/React.createElement(__ds_scope.Icon, {
    name: "loader-circle",
    size: iconSize,
    className: "kc-btn__spin"
  }) : iconLeft ? /*#__PURE__*/React.createElement(__ds_scope.Icon, {
    name: iconLeft,
    size: iconSize
  }) : null, children != null && children !== '' ? /*#__PURE__*/React.createElement("span", null, children) : null, iconRight && !loading ? /*#__PURE__*/React.createElement(__ds_scope.Icon, {
    name: iconRight,
    size: iconSize
  }) : null);
}
Object.assign(__ds_scope, { Button });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/button/Button.jsx", error: String((e && e.message) || e) }); }

// components/approval-card/ApprovalCard.jsx
try { (() => {
/** An action the copilot prepared that needs the owner's signature. */
function ApprovalCard({
  title,
  amount,
  onAmountClick,
  description,
  facts = [],
  limitNote,
  status = 'waiting',
  meta,
  resolvedNote,
  approveLabel = 'Sign and approve',
  declineLabel = 'Decline',
  onApprove,
  onDecline,
  className = ''
}) {
  const pending = status === 'waiting';
  return /*#__PURE__*/React.createElement("article", {
    className: `kc-approval kc-approval--${status} ${className}`
  }, /*#__PURE__*/React.createElement("div", {
    className: "kc-approval__top"
  }, /*#__PURE__*/React.createElement(__ds_scope.StatusPill, {
    status: status
  }), meta ? /*#__PURE__*/React.createElement("span", {
    className: "kc-caption"
  }, meta) : null), /*#__PURE__*/React.createElement("div", {
    className: "kc-approval__main"
  }, /*#__PURE__*/React.createElement("div", {
    className: "kc-approval__titles"
  }, /*#__PURE__*/React.createElement("h3", {
    className: "kc-section-title"
  }, title), description ? /*#__PURE__*/React.createElement("p", {
    className: "kc-approval__desc"
  }, description) : null), amount ? /*#__PURE__*/React.createElement("div", {
    className: "kc-approval__amount"
  }, onAmountClick ? /*#__PURE__*/React.createElement(__ds_scope.FactNumber, {
    onClick: onAmountClick
  }, amount) : amount) : null), facts.length ? /*#__PURE__*/React.createElement("dl", {
    className: "kc-approval__facts"
  }, facts.map((f, i) => /*#__PURE__*/React.createElement("div", {
    key: i,
    className: "kc-approval__fact"
  }, /*#__PURE__*/React.createElement("dt", null, f.label), /*#__PURE__*/React.createElement("dd", null, f.value)))) : null, limitNote ? /*#__PURE__*/React.createElement("div", {
    className: "kc-approval__limit"
  }, /*#__PURE__*/React.createElement(__ds_scope.Icon, {
    name: "shield-check",
    size: 16
  }), /*#__PURE__*/React.createElement("span", null, limitNote)) : null, pending ? /*#__PURE__*/React.createElement("div", {
    className: "kc-approval__actions"
  }, /*#__PURE__*/React.createElement(__ds_scope.Button, {
    variant: "primary",
    iconLeft: "pen-line",
    onClick: onApprove
  }, approveLabel), /*#__PURE__*/React.createElement(__ds_scope.Button, {
    variant: "secondary",
    onClick: onDecline
  }, declineLabel)) : resolvedNote ? /*#__PURE__*/React.createElement("div", {
    className: "kc-approval__resolved kc-caption"
  }, resolvedNote) : null);
}
Object.assign(__ds_scope, { ApprovalCard });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/approval-card/ApprovalCard.jsx", error: String((e && e.message) || e) }); }

// components/card/Card.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
/** Container. Maps to shadcn/ui Card. `improve` is the gold-outlined "one thing to improve" card. */
function Card({
  variant = 'default',
  eyebrow,
  title,
  description,
  action,
  footer,
  padding = 'md',
  children,
  className = '',
  ...rest
}) {
  const eb = eyebrow === undefined && variant === 'improve' ? 'One thing to improve' : eyebrow;
  return /*#__PURE__*/React.createElement("section", _extends({
    className: `kc-card kc-card--${variant} kc-card--pad-${padding} ${className}`
  }, rest), eb || title || action ? /*#__PURE__*/React.createElement("header", {
    className: "kc-card__head"
  }, /*#__PURE__*/React.createElement("div", {
    className: "kc-card__titles"
  }, eb ? /*#__PURE__*/React.createElement("div", {
    className: "kc-card__eyebrow"
  }, variant === 'improve' ? /*#__PURE__*/React.createElement(__ds_scope.Icon, {
    name: "coins",
    size: 16
  }) : null, /*#__PURE__*/React.createElement("span", null, eb)) : null, title ? /*#__PURE__*/React.createElement("h3", {
    className: "kc-section-title"
  }, title) : null, description ? /*#__PURE__*/React.createElement("p", {
    className: "kc-card__desc"
  }, description) : null), action ? /*#__PURE__*/React.createElement("div", {
    className: "kc-card__action"
  }, action) : null) : null, children ? /*#__PURE__*/React.createElement("div", {
    className: "kc-card__body"
  }, children) : null, footer ? /*#__PURE__*/React.createElement("footer", {
    className: "kc-card__foot"
  }, footer) : null);
}
Object.assign(__ds_scope, { Card });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/card/Card.jsx", error: String((e && e.message) || e) }); }

// components/kpi-tile/KpiTile.jsx
try { (() => {
/** Big KPI figure with label and delta. Value becomes a FactNumber when onTrace is given. */
function KpiTile({
  label,
  value,
  delta,
  caption,
  icon,
  size = 'lg',
  onTrace,
  source,
  className = ''
}) {
  const dTone = delta ? delta.tone || 'neutral' : null;
  const dIcon = dTone === 'good' ? 'trending-up' : dTone === 'bad' ? 'trending-down' : 'minus';
  return /*#__PURE__*/React.createElement("div", {
    className: `kc-kpi kc-kpi--${size} ${className}`
  }, /*#__PURE__*/React.createElement("div", {
    className: "kc-kpi__label"
  }, icon ? /*#__PURE__*/React.createElement(__ds_scope.Icon, {
    name: icon,
    size: 16
  }) : null, /*#__PURE__*/React.createElement("span", null, label)), /*#__PURE__*/React.createElement("div", {
    className: "kc-kpi__value"
  }, onTrace ? /*#__PURE__*/React.createElement(__ds_scope.FactNumber, {
    onClick: onTrace,
    source: source
  }, value) : value), delta || caption ? /*#__PURE__*/React.createElement("div", {
    className: "kc-kpi__foot"
  }, delta ? /*#__PURE__*/React.createElement("span", {
    className: `kc-kpi__delta kc-kpi__delta--${dTone}`
  }, /*#__PURE__*/React.createElement(__ds_scope.Icon, {
    name: dIcon,
    size: 14,
    strokeWidth: 2
  }), delta.label) : null, caption ? /*#__PURE__*/React.createElement("span", {
    className: "kc-caption"
  }, caption) : null) : null);
}
Object.assign(__ds_scope, { KpiTile });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/kpi-tile/KpiTile.jsx", error: String((e && e.message) || e) }); }

// components/progress/Progress.jsx
try { (() => {
/** Plain progress bar. Maps to shadcn/ui Progress. */
function Progress({
  value = 0,
  max = 100,
  tone = 'brand',
  size = 'md',
  label,
  className = ''
}) {
  const p = Math.max(0, Math.min(100, Number(value) / max * 100));
  return /*#__PURE__*/React.createElement("div", {
    className: `kc-progress kc-progress--${size} ${className}`,
    role: "progressbar",
    "aria-valuemin": 0,
    "aria-valuemax": max,
    "aria-valuenow": value,
    "aria-label": label
  }, /*#__PURE__*/React.createElement("div", {
    className: `kc-progress__fill kc-progress__fill--${tone}`,
    style: {
      width: p + '%'
    }
  }));
}
Object.assign(__ds_scope, { Progress });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/progress/Progress.jsx", error: String((e && e.message) || e) }); }

// components/progress/FactorBar.jsx
try { (() => {
/** Labelled factor bar: why an offer fits, how much of a limit is used, risk factors. */
function FactorBar({
  label,
  value = 0,
  max = 100,
  valueLabel,
  hint,
  tone = 'brand',
  threshold,
  thresholdLabel,
  className = ''
}) {
  const tp = threshold != null ? Math.max(0, Math.min(100, threshold / max * 100)) : null;
  return /*#__PURE__*/React.createElement("div", {
    className: `kc-factor ${className}`
  }, /*#__PURE__*/React.createElement("div", {
    className: "kc-factor__row"
  }, /*#__PURE__*/React.createElement("span", {
    className: "kc-factor__label"
  }, label), /*#__PURE__*/React.createElement("span", {
    className: "kc-factor__value"
  }, valueLabel ?? value)), /*#__PURE__*/React.createElement("div", {
    className: "kc-factor__track-wrap"
  }, /*#__PURE__*/React.createElement(__ds_scope.Progress, {
    value: value,
    max: max,
    tone: tone,
    size: "sm",
    label: label
  }), tp != null ? /*#__PURE__*/React.createElement("span", {
    className: "kc-factor__threshold",
    style: {
      left: tp + '%'
    },
    title: thresholdLabel
  }) : null), hint ? /*#__PURE__*/React.createElement("div", {
    className: "kc-caption"
  }, hint) : null);
}
Object.assign(__ds_scope, { FactorBar });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/progress/FactorBar.jsx", error: String((e && e.message) || e) }); }

// components/sheet/Sheet.jsx
try { (() => {
/** Side drawer. Maps to shadcn/ui Sheet. Used as the trace drawer behind FactNumber. */
function Sheet({
  open,
  onOpenChange,
  title,
  description,
  children,
  footer,
  side = 'right',
  width = 440,
  contained = false,
  className = ''
}) {
  React.useEffect(() => {
    if (!open) return;
    const onKey = e => {
      if (e.key === 'Escape') onOpenChange && onOpenChange(false);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, onOpenChange]);
  if (!open) return null;
  return /*#__PURE__*/React.createElement("div", {
    className: `kc-sheet${contained ? ' kc-sheet--contained' : ''} ${className}`
  }, /*#__PURE__*/React.createElement("div", {
    className: "kc-sheet__scrim",
    onClick: () => onOpenChange && onOpenChange(false)
  }), /*#__PURE__*/React.createElement("aside", {
    role: "dialog",
    "aria-modal": "true",
    "aria-label": typeof title === 'string' ? title : undefined,
    className: `kc-sheet__panel kc-sheet__panel--${side}`,
    style: {
      width
    }
  }, /*#__PURE__*/React.createElement("header", {
    className: "kc-sheet__head"
  }, /*#__PURE__*/React.createElement("div", {
    className: "kc-sheet__titles"
  }, title ? /*#__PURE__*/React.createElement("h2", {
    className: "kc-section-title"
  }, title) : null, description ? /*#__PURE__*/React.createElement("p", {
    className: "kc-sheet__desc"
  }, description) : null), /*#__PURE__*/React.createElement("button", {
    type: "button",
    className: "kc-sheet__close",
    "aria-label": "Close",
    onClick: () => onOpenChange && onOpenChange(false)
  }, /*#__PURE__*/React.createElement(__ds_scope.Icon, {
    name: "x",
    size: 20
  }))), /*#__PURE__*/React.createElement("div", {
    className: "kc-sheet__body"
  }, children), footer ? /*#__PURE__*/React.createElement("footer", {
    className: "kc-sheet__foot"
  }, footer) : null));
}
Object.assign(__ds_scope, { Sheet });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/sheet/Sheet.jsx", error: String((e && e.message) || e) }); }

// components/sheet/TraceStep.jsx
try { (() => {
/** One step in a trace: label, value, and source line. Use inside Sheet. */
function TraceStep({
  label,
  value,
  source,
  op,
  emphasis = false
}) {
  return /*#__PURE__*/React.createElement("div", {
    className: `kc-trace${emphasis ? ' kc-trace--total' : ''}`
  }, /*#__PURE__*/React.createElement("span", {
    className: "kc-trace__op"
  }, op || ''), /*#__PURE__*/React.createElement("div", {
    className: "kc-trace__main"
  }, /*#__PURE__*/React.createElement("div", {
    className: "kc-trace__label"
  }, label), source ? /*#__PURE__*/React.createElement("div", {
    className: "kc-trace__source"
  }, source) : null), /*#__PURE__*/React.createElement("span", {
    className: "kc-trace__value"
  }, value));
}
Object.assign(__ds_scope, { TraceStep });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/sheet/TraceStep.jsx", error: String((e && e.message) || e) }); }

// components/table/Table.jsx
try { (() => {
/** Data table. Maps to shadcn/ui Table. Numeric columns right-align with tabular figures. */
function Table({
  columns = [],
  rows = [],
  rowKey,
  onRowClick,
  density = 'regular',
  caption,
  empty = 'Nothing here yet.',
  className = ''
}) {
  return /*#__PURE__*/React.createElement("div", {
    className: `kc-table-wrap ${className}`
  }, /*#__PURE__*/React.createElement("table", {
    className: `kc-table kc-table--${density}`
  }, caption ? /*#__PURE__*/React.createElement("caption", {
    className: "kc-table__caption"
  }, caption) : null, /*#__PURE__*/React.createElement("thead", null, /*#__PURE__*/React.createElement("tr", null, columns.map(c => /*#__PURE__*/React.createElement("th", {
    key: c.key,
    style: {
      textAlign: c.align || 'left',
      width: c.width
    }
  }, c.header)))), /*#__PURE__*/React.createElement("tbody", null, rows.length === 0 ? /*#__PURE__*/React.createElement("tr", null, /*#__PURE__*/React.createElement("td", {
    colSpan: columns.length,
    className: "kc-table__empty"
  }, empty)) : rows.map((r, i) => /*#__PURE__*/React.createElement("tr", {
    key: rowKey ? r[rowKey] : i,
    onClick: onRowClick ? () => onRowClick(r) : undefined,
    className: onRowClick ? 'kc-table__row--click' : undefined
  }, columns.map(c => /*#__PURE__*/React.createElement("td", {
    key: c.key,
    style: {
      textAlign: c.align || 'left'
    },
    className: c.align === 'right' ? 'kc-table__num' : undefined
  }, c.render ? c.render(r) : r[c.key])))))));
}
Object.assign(__ds_scope, { Table });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/table/Table.jsx", error: String((e && e.message) || e) }); }

// components/tabs/Tabs.jsx
try { (() => {
/** Underline tabs. Maps to shadcn/ui Tabs (value / defaultValue / onValueChange). */
function Tabs({
  items = [],
  value,
  defaultValue,
  onValueChange,
  size = 'md',
  className = ''
}) {
  const [inner, setInner] = React.useState(defaultValue ?? (items[0] && items[0].value));
  const current = value ?? inner;
  const select = v => {
    if (value === undefined) setInner(v);
    onValueChange && onValueChange(v);
  };
  const onKey = (e, i) => {
    if (e.key !== 'ArrowRight' && e.key !== 'ArrowLeft') return;
    const n = (i + (e.key === 'ArrowRight' ? 1 : -1) + items.length) % items.length;
    select(items[n].value);
    const btns = e.currentTarget.parentElement.querySelectorAll('[role=tab]');
    btns[n] && btns[n].focus();
  };
  return /*#__PURE__*/React.createElement("div", {
    role: "tablist",
    className: `kc-tabs kc-tabs--${size} ${className}`
  }, items.map((t, i) => {
    const on = t.value === current;
    return /*#__PURE__*/React.createElement("button", {
      key: t.value,
      type: "button",
      role: "tab",
      "aria-selected": on,
      tabIndex: on ? 0 : -1,
      className: `kc-tabs__tab${on ? ' is-active' : ''}`,
      onClick: () => select(t.value),
      onKeyDown: e => onKey(e, i)
    }, /*#__PURE__*/React.createElement("span", null, t.label), t.count != null ? /*#__PURE__*/React.createElement("span", {
      className: "kc-tabs__count"
    }, t.count) : null);
  }));
}
Object.assign(__ds_scope, { Tabs });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/tabs/Tabs.jsx", error: String((e && e.message) || e) }); }

// components/tier-row/TierRow.jsx
try { (() => {
const MODES = {
  auto: {
    label: 'Acts on its own',
    icon: 'zap'
  },
  approval: {
    label: 'Asks first',
    icon: 'pen-line'
  },
  never: {
    label: 'Never',
    icon: 'ban'
  }
};

/** One permission tier the owner has signed: what the copilot may do, up to what amount, with which tools. */
function TierRow({
  tier,
  name,
  description,
  mode = 'approval',
  limit,
  tools = [],
  signedNote,
  onEdit,
  editLabel = 'Change limit',
  className = ''
}) {
  const m = MODES[mode] || MODES.approval;
  return /*#__PURE__*/React.createElement("div", {
    className: `kc-tier kc-tier--${mode} ${className}`
  }, /*#__PURE__*/React.createElement("div", {
    className: "kc-tier__num",
    "aria-label": `Tier ${tier}`
  }, tier), /*#__PURE__*/React.createElement("div", {
    className: "kc-tier__main"
  }, /*#__PURE__*/React.createElement("div", {
    className: "kc-tier__head"
  }, /*#__PURE__*/React.createElement("span", {
    className: "kc-tier__name"
  }, name), /*#__PURE__*/React.createElement("span", {
    className: `kc-tier__mode kc-tier__mode--${mode}`
  }, /*#__PURE__*/React.createElement(__ds_scope.Icon, {
    name: m.icon,
    size: 14,
    strokeWidth: 2
  }), m.label)), description ? /*#__PURE__*/React.createElement("p", {
    className: "kc-tier__desc"
  }, description) : null, tools.length ? /*#__PURE__*/React.createElement("ul", {
    className: "kc-tier__tools",
    "aria-label": "Tools"
  }, tools.map((t, i) => {
    const tool = typeof t === 'string' ? {
      label: t
    } : t;
    return /*#__PURE__*/React.createElement("li", {
      key: i,
      className: "kc-tier__tool"
    }, tool.icon ? /*#__PURE__*/React.createElement(__ds_scope.Icon, {
      name: tool.icon,
      size: 14
    }) : null, tool.label);
  })) : null, signedNote ? /*#__PURE__*/React.createElement("div", {
    className: "kc-caption kc-tier__signed"
  }, /*#__PURE__*/React.createElement(__ds_scope.Icon, {
    name: "signature",
    size: 14
  }), signedNote) : null), /*#__PURE__*/React.createElement("div", {
    className: "kc-tier__side"
  }, limit ? /*#__PURE__*/React.createElement("div", {
    className: "kc-tier__limit"
  }, /*#__PURE__*/React.createElement("span", {
    className: "kc-caption"
  }, "Limit"), /*#__PURE__*/React.createElement("span", {
    className: "kc-tier__limit-val"
  }, limit)) : null, onEdit ? /*#__PURE__*/React.createElement(__ds_scope.Button, {
    variant: "ghost",
    size: "sm",
    onClick: onEdit
  }, editLabel) : null));
}
Object.assign(__ds_scope, { TierRow });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/tier-row/TierRow.jsx", error: String((e && e.message) || e) }); }

// components/toast/Toast.jsx
try { (() => {
const ICONS = {
  default: 'info',
  success: 'circle-check',
  danger: 'ban',
  savings: 'coins'
};

/** Transient confirmation. Maps to shadcn/ui Toast / Sonner. Position it yourself (bottom-right). */
function Toast({
  variant = 'default',
  title,
  description,
  action,
  onClose,
  icon,
  className = ''
}) {
  return /*#__PURE__*/React.createElement("div", {
    role: "status",
    "aria-live": "polite",
    className: `kc-toast kc-toast--${variant} ${className}`
  }, /*#__PURE__*/React.createElement("span", {
    className: "kc-toast__icon"
  }, /*#__PURE__*/React.createElement(__ds_scope.Icon, {
    name: icon || ICONS[variant],
    size: 20
  })), /*#__PURE__*/React.createElement("div", {
    className: "kc-toast__content"
  }, title ? /*#__PURE__*/React.createElement("div", {
    className: "kc-toast__title"
  }, title) : null, description ? /*#__PURE__*/React.createElement("div", {
    className: "kc-toast__desc"
  }, description) : null), action ? /*#__PURE__*/React.createElement("button", {
    type: "button",
    className: "kc-toast__action",
    onClick: action.onClick
  }, action.label) : null, onClose ? /*#__PURE__*/React.createElement("button", {
    type: "button",
    className: "kc-toast__close",
    "aria-label": "Close",
    onClick: onClose
  }, /*#__PURE__*/React.createElement(__ds_scope.Icon, {
    name: "x",
    size: 16
  })) : null);
}
Object.assign(__ds_scope, { Toast });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/toast/Toast.jsx", error: String((e && e.message) || e) }); }

// ui_kits/app/chat.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
const CHAT_REPLIES = {
  flour: h => ({
    text: /*#__PURE__*/React.createElement(React.Fragment, null, "Yes. After payroll and rent you have ", h.fact('$4,280', 'safe'), " safe to spend. 40 bags from Fresh Farms is $1,080. Want me to prepare the order?")
  }),
  thursday: h => ({
    text: /*#__PURE__*/React.createElement(React.Fragment, null, "Payroll ($8,940) lands Oct 24 and rent ($2,600) the day after. Cash drops to about ", h.fact('$4,660', 'safe'), ". Still above your buffer."),
    attachment: /*#__PURE__*/React.createElement("div", {
      className: "kit-actions"
    }, /*#__PURE__*/React.createElement(h.Button, {
      variant: "secondary",
      size: "sm",
      iconLeft: "wallet",
      onClick: () => h.ctx.open('cash')
    }, "Open cash, next 30 days"))
  }),
  week: h => ({
    text: /*#__PURE__*/React.createElement(React.Fragment, null, "I categorized 38 transactions, sent one reminder, paid City Power, and blocked one payment that looked like fraud."),
    attachment: /*#__PURE__*/React.createElement("div", {
      className: "kit-actions"
    }, /*#__PURE__*/React.createElement(h.Button, {
      variant: "secondary",
      size: "sm",
      iconLeft: "shield-check",
      onClick: () => h.ctx.open('trust')
    }, "Open trust"))
  }),
  default: () => ({
    text: /*#__PURE__*/React.createElement(React.Fragment, null, "I checked your accounts. I don't have enough to answer that yet. Can you tell me which supplier or date you mean?")
  })
};
const chatPick = q => /flour|restock|afford/i.test(q) ? 'flour' : /thursday|tight/i.test(q) ? 'thursday' : /week|did you/i.test(q) ? 'week' : 'default';
function Conversation({
  ctx,
  seed,
  onSeedUsed
}) {
  const {
    ChatBubble,
    Button,
    FactNumber,
    AlertBanner,
    ApprovalCard,
    Badge
  } = window.KaChingDesignSystem_2fdbe1;
  const d = window.KC_DATA;
  const AV = '../../assets/logo-mark.png';
  const [msgs, setMsgs] = React.useState([{
    brief: 'lead'
  }, {
    brief: 'cash'
  }, {
    brief: 'tools'
  }]);
  const [text, setText] = React.useState('');
  const [thinking, setThinking] = React.useState(false);
  const [toolsPrepared, setToolsPrepared] = React.useState(false);
  const scroller = React.useRef(null);
  const fact = (v, key) => /*#__PURE__*/React.createElement(FactNumber, {
    onClick: () => ctx.trace(key)
  }, v);
  const h = {
    ctx,
    fact,
    Button
  };
  const now = () => new Date().toLocaleTimeString([], {
    hour: 'numeric',
    minute: '2-digit'
  }).toLowerCase();
  const send = q => {
    const body = (q ?? text).trim();
    if (!body) return;
    setMsgs(m => [...m, {
      role: 'owner',
      text: body,
      meta: now()
    }]);
    setText('');
    setThinking(true);
    setTimeout(() => {
      setThinking(false);
      setMsgs(m => [...m, {
        role: 'copilot',
        meta: now(),
        reply: chatPick(body)
      }]);
    }, 700);
  };
  React.useEffect(() => {
    if (seed) {
      send(seed);
      onSeedUsed();
    }
  }, [seed]);
  React.useEffect(() => {
    const el = scroller.current;
    if (el && msgs.length > 3) el.scrollTop = el.scrollHeight;
  }, [msgs, thinking]);
  const briefs = {
    lead: () => ({
      name: 'Morning brief · Friday, Oct 18',
      meta: '9:02 am',
      text: 'Morning, Maria. One invoice looks wrong, so I paused it. Two payments need your signature. Everything else is handled.',
      attachment: /*#__PURE__*/React.createElement("div", {
        className: "kit-attach"
      }, ctx.fraudOpen ? /*#__PURE__*/React.createElement(AlertBanner, {
        variant: "fraud",
        title: "Northside Packaging's bank details changed",
        actions: /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement(Button, {
          variant: "destructive",
          size: "sm",
          iconLeft: "ban",
          onClick: ctx.blockFraud
        }, "Keep payment blocked"), /*#__PURE__*/React.createElement(Button, {
          variant: "secondary",
          size: "sm",
          onClick: () => ctx.openInvoice('i2')
        }, "Review invoice"))
      }, "Invoice #7710 asks for account \xB7\xB78812. Their last 14 invoices used \xB7\xB73307. I paused the $2,980.00 payment until you check with them.") : null, d.approvals.map(a => {
        const st = ctx.approvalState[a.id] || 'waiting';
        return /*#__PURE__*/React.createElement(ApprovalCard, _extends({
          key: a.id
        }, a, {
          status: st,
          onAmountClick: a.trace ? () => ctx.trace(a.trace) : undefined,
          approveLabel: a.id === 'a2' ? 'Send reminder' : 'Sign and approve',
          resolvedNote: st === 'executed' ? 'Signed by you just now.' : 'Declined. Nothing was sent.',
          onApprove: () => ctx.approve(a),
          onDecline: () => ctx.decline(a)
        }));
      }))
    }),
    cash: () => ({
      text: /*#__PURE__*/React.createElement(React.Fragment, null, "Cash stays above your $1,000 buffer all month. The low point is $3,100 on Nov 11, after payroll and rent. Through Oct 25 you can spend ", fact('$4,280', 'safe'), "."),
      attachment: /*#__PURE__*/React.createElement("div", {
        className: "kit-actions"
      }, /*#__PURE__*/React.createElement(Button, {
        variant: "secondary",
        size: "sm",
        iconLeft: "wallet",
        onClick: () => ctx.open('cash')
      }, "Open cash, next 30 days"))
    }),
    tools: () => ({
      text: toolsPrepared ? 'The cancellation for Canva and Loom is ready. Sign it in Trust or tell me here.' : 'You pay $86 a month for Canva and Loom. Nobody on your team has opened either since June. Want me to prepare the cancellation?',
      attachment: toolsPrepared ? null : /*#__PURE__*/React.createElement("div", {
        className: "kit-actions"
      }, /*#__PURE__*/React.createElement(Button, {
        variant: "secondary",
        size: "sm",
        iconLeft: "circle-slash",
        onClick: () => {
          setToolsPrepared(true);
          ctx.toast({
            variant: 'savings',
            title: 'Cancellation prepared',
            description: 'Saves $86 a month once you sign.'
          });
        }
      }, "Prepare cancellation"), /*#__PURE__*/React.createElement(Badge, {
        variant: "savings"
      }, "Saves $86 a month"))
    })
  };
  return /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement("div", {
    className: "kit-scroll",
    ref: scroller
  }, /*#__PURE__*/React.createElement("div", {
    className: "kit-col kit-msgs",
    role: "log",
    "aria-label": "Conversation with KaChing"
  }, msgs.map((m, i) => {
    if (m.brief) {
      const b = briefs[m.brief]();
      return /*#__PURE__*/React.createElement(ChatBubble, {
        key: i,
        role: "copilot",
        name: b.name,
        meta: b.meta,
        attachment: b.attachment,
        avatarSrc: AV
      }, b.text);
    }
    if (m.reply) {
      const r = CHAT_REPLIES[m.reply](h);
      return /*#__PURE__*/React.createElement(ChatBubble, {
        key: i,
        role: "copilot",
        meta: m.meta,
        attachment: r.attachment,
        avatarSrc: AV
      }, r.text);
    }
    return /*#__PURE__*/React.createElement(ChatBubble, {
      key: i,
      role: "owner",
      meta: m.meta
    }, m.text);
  }), thinking ? /*#__PURE__*/React.createElement(ChatBubble, {
    role: "copilot",
    avatarSrc: AV
  }, /*#__PURE__*/React.createElement("span", {
    className: "kc-caption"
  }, "Checking your accounts\u2026")) : null)), /*#__PURE__*/React.createElement("div", {
    className: "kit-dock"
  }, /*#__PURE__*/React.createElement("div", {
    className: "kit-col"
  }, /*#__PURE__*/React.createElement("div", {
    className: "kit-sugg"
  }, d.suggestions.map(s => /*#__PURE__*/React.createElement("button", {
    key: s,
    className: "kit-chip",
    onClick: () => send(s)
  }, s))), /*#__PURE__*/React.createElement("form", {
    className: "kit-compose",
    onSubmit: e => {
      e.preventDefault();
      send();
    }
  }, /*#__PURE__*/React.createElement("input", {
    value: text,
    onChange: e => setText(e.target.value),
    placeholder: "Ask about your money",
    "aria-label": "Message"
  }), /*#__PURE__*/React.createElement(Button, {
    type: "submit",
    size: "sm",
    iconLeft: "arrow-up",
    "aria-label": "Send",
    disabled: !text.trim()
  })), /*#__PURE__*/React.createElement("div", {
    className: "kc-caption kit-dock__note"
  }, "KaChing acts only within the limits you signed."))));
}
window.Conversation = Conversation;
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/app/chat.jsx", error: String((e && e.message) || e) }); }

// ui_kits/app/data.js
try { (() => {
window.KC_DATA = {
  owner: {
    first: 'Maria',
    shop: 'Lopez Bakery',
    initials: 'ML'
  },
  traces: {
    cash: {
      title: 'Cash on hand',
      description: 'As of Oct 18, 9:02 am',
      steps: [{
        label: 'Checking ··4410',
        source: 'Bank feed, synced 9:02 am',
        value: '$14,980'
      }, {
        op: '+',
        label: 'Savings ··2208',
        source: 'Bank feed, synced 9:02 am',
        value: '$4,100'
      }, {
        op: '−',
        label: 'Pending card charges',
        source: '3 transactions, Oct 17',
        value: '$840'
      }, {
        op: '=',
        label: 'Cash on hand',
        value: '$18,240',
        emphasis: true
      }]
    },
    safe: {
      title: 'Safe to spend',
      description: 'Through Friday, Oct 25',
      steps: [{
        label: 'Cash on hand',
        source: 'See cash trace',
        value: '$18,240'
      }, {
        op: '−',
        label: 'Payroll, Oct 24',
        source: 'Gusto schedule',
        value: '$8,940'
      }, {
        op: '−',
        label: 'Rent, Oct 25',
        source: 'Recurring, 14 months',
        value: '$2,600'
      }, {
        op: '−',
        label: 'Bills due in 7 days',
        source: '4 invoices',
        value: '$1,420'
      }, {
        op: '−',
        label: 'Cash buffer you set',
        source: 'Settings, Sep 2',
        value: '$1,000'
      }, {
        op: '=',
        label: 'Safe to spend',
        value: '$4,280',
        emphasis: true
      }]
    },
    found: {
      title: 'Found this month',
      description: 'Money KaChing found or saved in October',
      steps: [{
        label: 'Unused software (Canva, Loom)',
        source: 'No logins since June',
        value: '$86'
      }, {
        op: '+',
        label: 'Duplicate charge, City Power',
        source: 'Refund requested Oct 9',
        value: '$154'
      }, {
        op: '+',
        label: 'Early-pay discount, Fresh Farms',
        source: '2% on invoice #2278',
        value: '$100'
      }, {
        op: '=',
        label: 'Found this month',
        value: '$340',
        emphasis: true
      }]
    },
    ff: {
      title: 'Fresh Farms invoice #2291',
      description: 'Why this amount',
      steps: [{
        label: 'Flour, 40 bags',
        source: 'PO #1180, received Oct 14',
        value: '$1,080.00'
      }, {
        op: '+',
        label: 'Butter, 12 cases',
        source: 'PO #1180, received Oct 14',
        value: '$184.80'
      }, {
        op: '−',
        label: 'Early-pay discount, 2%',
        source: 'Terms: 2/10 net 30',
        value: '$24.80'
      }, {
        op: '=',
        label: 'Amount to pay',
        value: '$1,240.00',
        emphasis: true
      }]
    }
  },
  approvals: [{
    id: 'a1',
    title: 'Pay Fresh Farms invoice #2291',
    amount: '$1,240.00',
    trace: 'ff',
    description: 'Matches the delivery on Oct 14. Paying today keeps your 2% early discount.',
    facts: [{
      label: 'Due',
      value: 'Oct 21'
    }, {
      label: 'From',
      value: 'Checking ··4410'
    }, {
      label: 'Saves',
      value: '$24.80'
    }],
    limitNote: 'Within your $2,000 Ask first limit',
    meta: 'Prepared 9:14 am'
  }, {
    id: 'a2',
    title: 'Send reminder to Hillside Café',
    amount: '$640.00',
    description: 'Invoice #1043 is 12 days late. They usually pay within 3 days of a reminder.',
    facts: [{
      label: 'Overdue',
      value: '12 days'
    }, {
      label: 'Channel',
      value: 'Email'
    }],
    limitNote: 'Reminders over 10 days late ask first',
    meta: 'Prepared 8:50 am'
  }],
  recent: [{
    what: 'Categorized 38 transactions',
    when: '8:31 am',
    status: 'executed'
  }, {
    what: 'Sent reminder to Oak St. Deli',
    when: 'Yesterday',
    status: 'executed'
  }, {
    what: 'Paid City Power $311.47',
    when: 'Oct 16',
    status: 'executed'
  }, {
    what: 'Payment to Northside Packaging',
    when: 'Oct 16',
    status: 'blocked'
  }],
  forecast: [18240, 17900, 17420, 17800, 18350, 16900, 16200, 7260, 4660, 5100, 5800, 6420, 7010, 7400, 8100, 8600, 8200, 8900, 9500, 10200, 9900, 10600, 11200, 11800, 3100, 3600, 4400, 5200, 5900, 6500],
  upcoming: [{
    id: 1,
    date: 'Oct 21',
    what: 'Fresh Farms',
    kind: 'Bill',
    status: 'waiting',
    amount: '−$1,240.00'
  }, {
    id: 2,
    date: 'Oct 22',
    what: 'Square deposits (est.)',
    kind: 'Income',
    status: 'executed',
    amount: '+$3,180.00'
  }, {
    id: 3,
    date: 'Oct 24',
    what: 'Payroll',
    kind: 'Payroll',
    status: 'executed',
    amount: '−$8,940.00'
  }, {
    id: 4,
    date: 'Oct 25',
    what: 'Rent, 412 Main St',
    kind: 'Bill',
    status: 'executed',
    amount: '−$2,600.00'
  }, {
    id: 5,
    date: 'Oct 28',
    what: 'Hillside Café',
    kind: 'Receivable',
    status: 'waiting',
    amount: '+$640.00'
  }],
  invoices: [{
    id: 'i1',
    vendor: 'Fresh Farms',
    inv: '#2291',
    received: 'Oct 15',
    due: 'Oct 21',
    status: 'waiting',
    amount: '$1,240.00',
    tab: 'open',
    check: 'Matches PO #1180 and delivery'
  }, {
    id: 'i2',
    vendor: 'Northside Packaging',
    inv: '#7710',
    received: 'Oct 16',
    due: 'Oct 22',
    status: 'blocked',
    amount: '$2,980.00',
    tab: 'flagged',
    check: 'Bank details changed'
  }, {
    id: 'i3',
    vendor: 'Bluebird Linen',
    inv: '#0419',
    received: 'Oct 12',
    due: 'Oct 30',
    status: 'waiting',
    amount: '$96.20',
    tab: 'open',
    check: 'Matches last 9 invoices'
  }, {
    id: 'i4',
    vendor: 'City Power',
    inv: '#88-102',
    received: 'Oct 3',
    due: 'Oct 19',
    status: 'executed',
    amount: '$311.47',
    tab: 'paid',
    check: 'Recurring, amount in usual range'
  }, {
    id: 'i5',
    vendor: 'Valley Dairy',
    inv: '#5521',
    received: 'Oct 1',
    due: 'Oct 15',
    status: 'executed',
    amount: '$728.00',
    tab: 'paid',
    check: 'Matches PO #1172'
  }],
  offers: [{
    id: 'o1',
    lender: 'Main Street Credit Union',
    product: 'Equipment loan',
    amount: '$25,000',
    apr: '8.9%',
    monthly: '$518',
    term: '60 months',
    fit: 'fits',
    factors: [{
      label: 'Repayment vs monthly cash buffer',
      value: 31,
      valueLabel: '31%',
      threshold: 50,
      hint: 'Under 50% is comfortable'
    }, {
      label: 'Time in business',
      value: 80,
      valueLabel: '4 years',
      tone: 'teal',
      hint: 'They ask for 2+'
    }]
  }, {
    id: 'o2',
    lender: 'SBA Microloan via Accion',
    product: 'Working capital',
    amount: '$15,000',
    apr: '11.5%',
    monthly: '$330',
    term: '72 months',
    fit: 'fits',
    factors: [{
      label: 'Repayment vs monthly cash buffer',
      value: 20,
      valueLabel: '20%',
      threshold: 50
    }, {
      label: 'Paperwork',
      value: 60,
      valueLabel: '6 documents',
      tone: 'neutral',
      hint: 'I can prepare 5 of 6'
    }]
  }, {
    id: 'o3',
    lender: 'QuickFund Merchant Advance',
    product: 'Cash advance',
    amount: '$20,000',
    apr: '54% est.',
    monthly: '$2,140',
    term: '10 months',
    fit: 'doesnt-fit',
    factors: [{
      label: 'Repayment vs monthly cash buffer',
      value: 88,
      valueLabel: '88%',
      tone: 'danger',
      threshold: 50,
      hint: 'Takes a daily cut of card sales'
    }]
  }],
  tiers: [{
    tier: 1,
    name: 'Everyday upkeep',
    mode: 'auto',
    limit: '$200 per action',
    description: 'Small, reversible jobs. KaChing tells you after.',
    tools: [{
      label: 'Categorize transactions',
      icon: 'tags'
    }, {
      label: 'Send reminders under 10 days late',
      icon: 'mail'
    }, {
      label: 'Request refunds for duplicates',
      icon: 'rotate-ccw'
    }]
  }, {
    tier: 2,
    name: 'Paying suppliers',
    mode: 'approval',
    limit: '$2,000 per action',
    description: 'KaChing prepares the payment. You sign it.',
    tools: [{
      label: 'Pay bills',
      icon: 'receipt'
    }, {
      label: 'Schedule transfers',
      icon: 'calendar'
    }, {
      label: 'Cancel subscriptions',
      icon: 'circle-slash'
    }]
  }, {
    tier: 3,
    name: 'Moving larger sums',
    mode: 'approval',
    limit: '$10,000 per action',
    description: 'Needs your signature and a second check by text.',
    tools: [{
      label: 'Transfer between accounts',
      icon: 'arrow-left-right'
    }]
  }, {
    tier: 4,
    name: 'Taking on debt',
    mode: 'never',
    description: 'KaChing can compare offers. It never applies or accepts.',
    tools: ['Accept loan offers', 'Open credit lines', 'Sign contracts']
  }],
  chat: [{
    role: 'copilot',
    text: 'Morning, Maria. Two things need your signature and one invoice looks wrong. Everything else is handled.',
    meta: '9:02 am'
  }],
  suggestions: ['Can I afford to restock flour?', 'Why is Thursday tight?', 'What did you do this week?']
};
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/app/data.js", error: String((e && e.message) || e) }); }

// ui_kits/app/detail-panel.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
const DETAIL_META = {
  cash: {
    title: 'Cash, next 30 days',
    desc: 'Forecast from your bank feed, payroll schedule and open invoices'
  },
  inbox: {
    title: 'Inbox',
    desc: 'Every invoice is checked before it is paid'
  },
  financing: {
    title: 'Financing',
    desc: 'Offers matched to your cash flow'
  },
  trust: {
    title: 'Trust',
    desc: 'What KaChing may do on its own, and what it did'
  }
};
function CashChart({
  data
}) {
  const W = 496,
    H = 200,
    P = {
      l: 40,
      r: 8,
      t: 20,
      b: 26
    };
  const max = 20000,
    n = data.length;
  const x = i => P.l + i / (n - 1) * (W - P.l - P.r);
  const y = v => P.t + (1 - v / max) * (H - P.t - P.b);
  const line = data.map((v, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(' ');
  const area = `${line} L${x(n - 1)},${y(0)} L${x(0)},${y(0)} Z`;
  const low = data.reduce((m, v, i) => v < data[m] ? i : m, 0);
  const t = {
    fontSize: 11,
    fill: 'var(--text-muted)',
    fontFamily: 'var(--font-body)'
  };
  return /*#__PURE__*/React.createElement("svg", {
    viewBox: `0 0 ${W} ${H}`,
    width: "100%",
    style: {
      display: 'block'
    },
    role: "img",
    "aria-label": "Cash forecast, next 30 days"
  }, [0, 5000, 10000, 15000, 20000].map(v => /*#__PURE__*/React.createElement("g", {
    key: v
  }, /*#__PURE__*/React.createElement("line", {
    x1: P.l,
    x2: W - P.r,
    y1: y(v),
    y2: y(v),
    stroke: "var(--border)",
    opacity: "0.6"
  }), /*#__PURE__*/React.createElement("text", _extends({
    x: P.l - 8,
    y: y(v) + 4,
    textAnchor: "end"
  }, t), "$", v / 1000, "k"))), /*#__PURE__*/React.createElement("line", {
    x1: P.l,
    x2: W - P.r,
    y1: y(1000),
    y2: y(1000),
    stroke: "var(--chart-3)",
    strokeDasharray: "4 5",
    strokeWidth: "1.25"
  }), /*#__PURE__*/React.createElement("text", _extends({
    x: P.l + 6,
    y: y(1000) - 6
  }, t), "Your $1,000 buffer"), /*#__PURE__*/React.createElement("path", {
    d: area,
    fill: "var(--chart-1)",
    opacity: "0.08"
  }), /*#__PURE__*/React.createElement("path", {
    d: line,
    fill: "none",
    stroke: "var(--chart-1)",
    strokeWidth: "2",
    strokeLinejoin: "round"
  }), /*#__PURE__*/React.createElement("circle", {
    cx: x(0),
    cy: y(data[0]),
    r: "4",
    fill: "var(--chart-1)"
  }), /*#__PURE__*/React.createElement("circle", {
    cx: x(low),
    cy: y(data[low]),
    r: "4",
    fill: "var(--surface-muted)",
    stroke: "var(--chart-1)",
    strokeWidth: "2"
  }), /*#__PURE__*/React.createElement("text", _extends({
    x: x(low),
    y: y(data[low]) - 10,
    textAnchor: "middle"
  }, t, {
    fontWeight: "500",
    fill: "var(--text)"
  }), "Low: $", data[low].toLocaleString()), ['Oct 18', 'Oct 25', 'Nov 1', 'Nov 8', 'Nov 16'].map((l, i) => /*#__PURE__*/React.createElement("text", _extends({
    key: l,
    x: x(Math.round(i / 4 * (n - 1))),
    y: H - 6,
    textAnchor: i === 0 ? 'start' : i === 4 ? 'end' : 'middle'
  }, t), l)));
}
function CashView({
  ctx
}) {
  const {
    Table,
    StatusPill,
    KpiTile,
    FactNumber
  } = window.KaChingDesignSystem_2fdbe1;
  const d = window.KC_DATA;
  return /*#__PURE__*/React.createElement("div", {
    className: "kit-stack",
    style: {
      gap: 40
    }
  }, /*#__PURE__*/React.createElement("section", {
    className: "kit-sec",
    style: {
      gap: 24
    }
  }, /*#__PURE__*/React.createElement("div", {
    className: "kit-kpis2"
  }, /*#__PURE__*/React.createElement(KpiTile, {
    size: "md",
    label: "Lowest point, Nov 11",
    value: "$3,100",
    delta: {
      label: 'Above your buffer',
      tone: 'good'
    }
  }), /*#__PURE__*/React.createElement(KpiTile, {
    size: "md",
    label: "Safe to spend",
    value: "$4,280",
    caption: "through Oct 25",
    onTrace: () => ctx.trace('safe')
  })), /*#__PURE__*/React.createElement(CashChart, {
    data: d.forecast
  }), /*#__PURE__*/React.createElement("p", {
    className: "kit-p",
    style: {
      color: 'var(--text-muted)'
    }
  }, "Thursday is tight because payroll and rent land the same week. You stay above your buffer. If Hillside Caf\xE9 pays on time you'll have ", /*#__PURE__*/React.createElement(FactNumber, {
    onClick: () => ctx.trace('safe')
  }, "$640"), " more.")), /*#__PURE__*/React.createElement("section", {
    className: "kit-sec"
  }, /*#__PURE__*/React.createElement("div", {
    className: "kit-sechead"
  }, /*#__PURE__*/React.createElement("h3", {
    className: "kc-section-title"
  }, "Coming up"), /*#__PURE__*/React.createElement("span", {
    className: "kc-caption"
  }, "Next 10 days")), /*#__PURE__*/React.createElement(Table, {
    rowKey: "id",
    columns: [{
      key: 'date',
      header: 'Date',
      width: 72
    }, {
      key: 'what',
      header: 'What',
      render: r => /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("div", {
        style: {
          fontWeight: 500
        }
      }, r.what), /*#__PURE__*/React.createElement("div", {
        className: "kc-caption"
      }, r.kind))
    }, {
      key: 'status',
      header: 'Status',
      render: r => /*#__PURE__*/React.createElement(StatusPill, {
        size: "sm",
        status: r.status,
        label: r.status === 'executed' ? 'Scheduled' : undefined
      })
    }, {
      key: 'amount',
      header: 'Amount',
      align: 'right',
      render: r => /*#__PURE__*/React.createElement("span", {
        style: {
          color: r.amount.startsWith('+') ? 'var(--success)' : 'var(--text)'
        }
      }, r.amount)
    }],
    rows: d.upcoming
  })));
}
function DetailPanel({
  ctx,
  view
}) {
  const {
    Button
  } = window.KaChingDesignSystem_2fdbe1;
  const [shown, setShown] = React.useState(view);
  const body = React.useRef(null);
  const inv = ctx.invoice;
  React.useEffect(() => {
    if (view) setShown(view);
  }, [view]);
  React.useEffect(() => {
    if (body.current) body.current.scrollTop = 0;
  }, [shown, inv]);
  const m = shown ? DETAIL_META[shown] : null;
  let title = m && m.title,
    desc = m && m.desc,
    content = null,
    foot = null;
  if (shown === 'cash') content = /*#__PURE__*/React.createElement(CashView, {
    ctx: ctx
  });
  if (shown === 'financing') content = /*#__PURE__*/React.createElement(FinancingView, {
    ctx: ctx
  });
  if (shown === 'trust') content = /*#__PURE__*/React.createElement(TrustView, {
    ctx: ctx
  });
  const onInvoice = shown === 'inbox' && inv;
  if (shown === 'inbox') {
    if (inv) {
      title = `${inv.vendor} ${inv.inv}`;
      desc = 'Invoice details and checks';
      content = /*#__PURE__*/React.createElement(InvoiceBody, {
        inv: inv
      });
      foot = inv.status === 'blocked' ? /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement(Button, {
        variant: "destructive",
        size: "sm",
        iconLeft: "ban",
        onClick: () => {
          ctx.setInvoice(null);
          ctx.blockFraud();
        }
      }, "Keep blocked"), /*#__PURE__*/React.createElement(Button, {
        variant: "secondary",
        size: "sm",
        onClick: () => ctx.toast({
          title: 'Call scheduled',
          description: 'Reminder set for 10:00 am.'
        })
      }, "Call supplier first")) : inv.status === 'waiting' ? /*#__PURE__*/React.createElement(Button, {
        size: "sm",
        iconLeft: "pen-line",
        onClick: () => {
          ctx.setInvoice(null);
          inv.id === 'i1' ? ctx.approve(window.KC_DATA.approvals[0]) : ctx.toast({
            variant: 'success',
            title: 'Payment scheduled',
            description: `${inv.amount} to ${inv.vendor}`
          });
        }
      }, "Sign and approve") : null;
    } else content = /*#__PURE__*/React.createElement(InboxView, {
      ctx: ctx
    });
  }
  return /*#__PURE__*/React.createElement("aside", {
    className: "kit-detail",
    "aria-label": title,
    "aria-hidden": !view,
    "data-screen-label": `Detail: ${title || 'closed'}`
  }, /*#__PURE__*/React.createElement("header", {
    className: "kit-detail__head"
  }, onInvoice ? /*#__PURE__*/React.createElement(Button, {
    variant: "ghost",
    size: "sm",
    iconLeft: "arrow-left",
    "aria-label": "Back to inbox",
    onClick: () => ctx.setInvoice(null)
  }) : null, /*#__PURE__*/React.createElement("div", {
    className: "kit-detail__titles"
  }, /*#__PURE__*/React.createElement("h2", {
    className: "kc-page-title"
  }, title), desc ? /*#__PURE__*/React.createElement("div", {
    className: "kc-caption"
  }, desc) : null), /*#__PURE__*/React.createElement(Button, {
    variant: "ghost",
    size: "sm",
    iconLeft: "x",
    "aria-label": "Close panel",
    onClick: ctx.close
  })), /*#__PURE__*/React.createElement("div", {
    className: "kit-detail__body",
    ref: body
  }, content), foot ? /*#__PURE__*/React.createElement("footer", {
    className: "kit-detail__foot"
  }, foot) : null);
}
Object.assign(window, {
  DetailPanel,
  CashChart
});
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/app/detail-panel.jsx", error: String((e && e.message) || e) }); }

// ui_kits/app/detail-views.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
function InboxView({
  ctx
}) {
  const {
    Tabs,
    Table,
    StatusPill,
    AlertBanner,
    Button
  } = window.KaChingDesignSystem_2fdbe1;
  const d = window.KC_DATA;
  const [tab, setTab] = React.useState('open');
  const count = t => d.invoices.filter(i => i.tab === t).length;
  const rows = tab === 'all' ? d.invoices : d.invoices.filter(i => i.tab === tab);
  return /*#__PURE__*/React.createElement("div", {
    className: "kit-stack"
  }, ctx.fraudOpen && tab !== 'flagged' ? /*#__PURE__*/React.createElement(AlertBanner, {
    variant: "fraud",
    title: "1 invoice is on hold",
    actions: /*#__PURE__*/React.createElement(Button, {
      variant: "secondary",
      size: "sm",
      onClick: () => setTab('flagged')
    }, "Show flagged")
  }, "Northside Packaging #7710 changed bank details. Payment stays blocked until you confirm.") : null, /*#__PURE__*/React.createElement("div", {
    className: "kit-sec"
  }, /*#__PURE__*/React.createElement(Tabs, {
    value: tab,
    onValueChange: setTab,
    items: [{
      value: 'open',
      label: 'Open',
      count: count('open')
    }, {
      value: 'flagged',
      label: 'Flagged',
      count: count('flagged')
    }, {
      value: 'paid',
      label: 'Paid'
    }, {
      value: 'all',
      label: 'All'
    }]
  }), /*#__PURE__*/React.createElement(Table, {
    rowKey: "id",
    onRowClick: ctx.setInvoice,
    columns: [{
      key: 'vendor',
      header: 'Supplier',
      render: r => /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("div", {
        style: {
          fontWeight: 500
        }
      }, r.vendor), /*#__PURE__*/React.createElement("div", {
        className: "kc-caption",
        style: {
          color: r.status === 'blocked' ? 'var(--danger)' : undefined
        }
      }, r.inv, " \xB7 ", r.check))
    }, {
      key: 'status',
      header: 'Status',
      render: r => /*#__PURE__*/React.createElement(StatusPill, {
        size: "sm",
        status: r.status
      })
    }, {
      key: 'amount',
      header: 'Amount',
      align: 'right'
    }],
    rows: rows,
    empty: "No invoices here."
  })));
}
function InvoiceBody({
  inv
}) {
  const {
    AlertBanner,
    TraceStep,
    StatusPill
  } = window.KaChingDesignSystem_2fdbe1;
  const fraud = inv.status === 'blocked';
  return /*#__PURE__*/React.createElement("div", {
    className: "kit-stack",
    style: {
      gap: 20
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      justifyContent: 'space-between',
      alignItems: 'center'
    }
  }, /*#__PURE__*/React.createElement(StatusPill, {
    status: inv.status
  }), /*#__PURE__*/React.createElement("span", {
    className: "kc-display-number",
    style: {
      fontSize: 32,
      lineHeight: '38px'
    }
  }, inv.amount)), fraud ? /*#__PURE__*/React.createElement(AlertBanner, {
    variant: "fraud",
    title: "Bank details changed"
  }, "Requested account \xB7\xB78812. Previous 14 invoices: \xB7\xB73307. The email came from northside-packing.co, not northsidepackaging.com.") : null, /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("h3", {
    className: "kc-section-title",
    style: {
      marginBottom: 4
    }
  }, "Checks"), /*#__PURE__*/React.createElement(TraceStep, {
    label: "Supplier known",
    source: "23 invoices since 2023",
    value: /*#__PURE__*/React.createElement(StatusPill, {
      size: "sm",
      status: "fits",
      label: "Pass"
    })
  }), /*#__PURE__*/React.createElement(TraceStep, {
    label: "Amount in usual range",
    source: "Median $2,710",
    value: /*#__PURE__*/React.createElement(StatusPill, {
      size: "sm",
      status: "fits",
      label: "Pass"
    })
  }), /*#__PURE__*/React.createElement(TraceStep, {
    label: "Bank account matches history",
    source: "Compared to last 14 invoices",
    value: fraud ? /*#__PURE__*/React.createElement(StatusPill, {
      size: "sm",
      status: "blocked",
      label: "Fail"
    }) : /*#__PURE__*/React.createElement(StatusPill, {
      size: "sm",
      status: "fits",
      label: "Pass"
    })
  }), /*#__PURE__*/React.createElement(TraceStep, {
    label: "Matches a purchase order",
    source: fraud ? 'PO #1176' : 'PO #1180',
    value: /*#__PURE__*/React.createElement(StatusPill, {
      size: "sm",
      status: "fits",
      label: "Pass"
    })
  })), /*#__PURE__*/React.createElement("div", {
    className: "kc-caption"
  }, "Received ", inv.received, ". Due ", inv.due, "."));
}
function FinancingView({
  ctx
}) {
  const {
    Card,
    StatusPill,
    FactorBar,
    Button,
    AlertBanner
  } = window.KaChingDesignSystem_2fdbe1;
  const d = window.KC_DATA;
  return /*#__PURE__*/React.createElement("div", {
    className: "kit-stack",
    style: {
      gap: 16
    }
  }, /*#__PURE__*/React.createElement(AlertBanner, {
    variant: "info",
    eyebrow: "How this works",
    title: "KaChing compares offers. It never applies."
  }, "Taking on debt is set to Never in your limits. I can prepare the paperwork; you send it yourself."), d.offers.map(o => /*#__PURE__*/React.createElement(Card, {
    key: o.id,
    variant: "muted",
    eyebrow: o.product,
    title: o.lender,
    action: /*#__PURE__*/React.createElement(StatusPill, {
      status: o.fit
    }),
    footer: o.fit === 'fits' ? /*#__PURE__*/React.createElement(Button, {
      size: "sm",
      iconLeft: "file-text",
      onClick: () => ctx.toast({
        title: 'Application drafted',
        description: `${o.lender}. Review it before you send.`
      })
    }, "Prepare application") : /*#__PURE__*/React.createElement(Button, {
      size: "sm",
      variant: "ghost",
      onClick: () => ctx.ask(`Why doesn't ${o.lender} fit?`)
    }, "Ask why in chat")
  }, /*#__PURE__*/React.createElement("dl", {
    className: "kit-terms",
    style: {
      gridTemplateColumns: 'repeat(4,minmax(0,1fr))'
    }
  }, /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("dt", null, "Amount"), /*#__PURE__*/React.createElement("dd", {
    className: "kit-terms__big"
  }, o.amount)), /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("dt", null, "APR"), /*#__PURE__*/React.createElement("dd", null, o.apr)), /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("dt", null, "Monthly"), /*#__PURE__*/React.createElement("dd", null, o.monthly)), /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("dt", null, "Term"), /*#__PURE__*/React.createElement("dd", null, o.term))), /*#__PURE__*/React.createElement("div", {
    className: "kit-stack",
    style: {
      gap: 12,
      marginTop: 16
    }
  }, o.factors.map((f, i) => /*#__PURE__*/React.createElement(FactorBar, _extends({
    key: i
  }, f)))))));
}
function TrustView({
  ctx
}) {
  const {
    TierRow,
    Button,
    FactorBar,
    StatusPill
  } = window.KaChingDesignSystem_2fdbe1;
  const d = window.KC_DATA;
  return /*#__PURE__*/React.createElement("div", {
    className: "kit-stack",
    style: {
      gap: 40
    }
  }, /*#__PURE__*/React.createElement("section", {
    className: "kit-sec",
    style: {
      gap: 4
    }
  }, /*#__PURE__*/React.createElement("div", {
    className: "kit-sechead"
  }, /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("h3", {
    className: "kc-section-title"
  }, "What KaChing may do"), /*#__PURE__*/React.createElement("div", {
    className: "kc-caption",
    style: {
      marginTop: 4
    }
  }, "Signed by Maria Lopez on Sep 2. Nothing above these limits happens without a new signature.")), /*#__PURE__*/React.createElement(Button, {
    variant: "secondary",
    size: "sm",
    iconLeft: "pen-line",
    onClick: () => ctx.toast({
      title: 'Draft ready',
      description: 'Change a limit, then sign to apply it.'
    })
  }, "Change limits")), /*#__PURE__*/React.createElement("div", null, d.tiers.map(t => /*#__PURE__*/React.createElement(TierRow, _extends({
    key: t.tier
  }, t))))), /*#__PURE__*/React.createElement("section", {
    className: "kit-sec",
    style: {
      gap: 16
    }
  }, /*#__PURE__*/React.createElement("h3", {
    className: "kc-section-title"
  }, "This month"), /*#__PURE__*/React.createElement(FactorBar, {
    label: "Acted on its own",
    value: 148,
    max: 600,
    valueLabel: "$148 of $600",
    hint: "38 actions, all under $200"
  }), /*#__PURE__*/React.createElement(FactorBar, {
    label: "Signed by you",
    value: 3480,
    max: 10000,
    valueLabel: "$3,480",
    tone: "teal",
    hint: "6 approvals"
  }), /*#__PURE__*/React.createElement(FactorBar, {
    label: "Blocked",
    value: 1,
    max: 10,
    valueLabel: "1 payment",
    tone: "danger",
    hint: "Northside Packaging, $2,980"
  })), /*#__PURE__*/React.createElement("section", {
    className: "kit-sec",
    style: {
      gap: 16
    }
  }, /*#__PURE__*/React.createElement("h3", {
    className: "kc-section-title"
  }, "What KaChing did"), /*#__PURE__*/React.createElement("ul", {
    className: "kit-list"
  }, d.recent.map((r, i) => /*#__PURE__*/React.createElement("li", {
    key: i
  }, /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("div", {
    className: "kit-list__what"
  }, r.what), /*#__PURE__*/React.createElement("div", {
    className: "kc-caption"
  }, r.when)), /*#__PURE__*/React.createElement(StatusPill, {
    size: "sm",
    status: r.status
  })))), /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement(Button, {
    variant: "ghost",
    size: "sm",
    iconRight: "arrow-right",
    onClick: () => ctx.trace('found')
  }, "See an example trace"))));
}
Object.assign(window, {
  InboxView,
  InvoiceBody,
  FinancingView,
  TrustView
});
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/app/detail-views.jsx", error: String((e && e.message) || e) }); }

// ui_kits/app/rail.jsx
try { (() => {
const RAIL_VIEWS = [{
  id: 'cash',
  label: 'Cash, next 30 days',
  icon: 'wallet'
}, {
  id: 'inbox',
  label: 'Inbox',
  icon: 'inbox',
  flagged: true
}, {
  id: 'financing',
  label: 'Financing',
  icon: 'landmark',
  meta: '2 fit'
}, {
  id: 'trust',
  label: 'Trust',
  icon: 'shield-check',
  meta: 'Signed Sep 2'
}];
function Rail({
  ctx
}) {
  const {
    KpiTile,
    Icon,
    StatusPill
  } = window.KaChingDesignSystem_2fdbe1;
  const d = window.KC_DATA;
  return /*#__PURE__*/React.createElement("aside", {
    className: "kit-rail",
    "aria-label": "Today at a glance",
    "data-screen-label": "Rail"
  }, /*#__PURE__*/React.createElement("div", {
    className: "kit-rail__stats"
  }, /*#__PURE__*/React.createElement(KpiTile, {
    size: "md",
    label: "Cash on hand",
    value: "$18,240",
    delta: {
      label: '+$1,120',
      tone: 'good'
    },
    caption: "vs last Friday",
    onTrace: () => ctx.trace('cash'),
    source: "Bank feed, 2 accounts"
  }), /*#__PURE__*/React.createElement(KpiTile, {
    size: "md",
    label: "Safe to spend",
    value: "$4,280",
    caption: "through Oct 25",
    onTrace: () => ctx.trace('safe')
  }), /*#__PURE__*/React.createElement(KpiTile, {
    size: "md",
    label: "Found this month",
    value: "$340",
    caption: "3 sources",
    onTrace: () => ctx.trace('found')
  })), /*#__PURE__*/React.createElement("nav", {
    className: "kit-rail__nav",
    "aria-label": "Open a view"
  }, RAIL_VIEWS.map(v => /*#__PURE__*/React.createElement("button", {
    key: v.id,
    className: "kit-railnav",
    onClick: () => ctx.open(v.id)
  }, /*#__PURE__*/React.createElement(Icon, {
    name: v.icon,
    size: 20
  }), /*#__PURE__*/React.createElement("span", null, v.label), v.flagged && ctx.fraudOpen ? /*#__PURE__*/React.createElement("span", {
    className: "kit-railnav__count",
    "aria-label": "1 flagged"
  }, "1") : v.meta ? /*#__PURE__*/React.createElement("span", {
    className: "kit-railnav__meta"
  }, v.meta) : null))), /*#__PURE__*/React.createElement("div", {
    className: "kit-rail__foot"
  }, /*#__PURE__*/React.createElement(StatusPill, {
    status: "synthetic",
    size: "sm"
  }), /*#__PURE__*/React.createElement("div", {
    className: "kit-shop"
  }, /*#__PURE__*/React.createElement("span", {
    className: "kit-shop__av"
  }, d.owner.initials), /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("div", {
    className: "kit-shop__name"
  }, d.owner.shop), /*#__PURE__*/React.createElement("div", {
    className: "kc-caption"
  }, "Maria Lopez, owner")))));
}
window.Rail = Rail;
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/app/rail.jsx", error: String((e && e.message) || e) }); }

__ds_ns.AlertBanner = __ds_scope.AlertBanner;

__ds_ns.ApprovalCard = __ds_scope.ApprovalCard;

__ds_ns.Badge = __ds_scope.Badge;

__ds_ns.StatusPill = __ds_scope.StatusPill;

__ds_ns.Button = __ds_scope.Button;

__ds_ns.Card = __ds_scope.Card;

__ds_ns.ChatBubble = __ds_scope.ChatBubble;

__ds_ns.FactNumber = __ds_scope.FactNumber;

__ds_ns.Icon = __ds_scope.Icon;

__ds_ns.KpiTile = __ds_scope.KpiTile;

__ds_ns.FactorBar = __ds_scope.FactorBar;

__ds_ns.Progress = __ds_scope.Progress;

__ds_ns.Sheet = __ds_scope.Sheet;

__ds_ns.TraceStep = __ds_scope.TraceStep;

__ds_ns.Table = __ds_scope.Table;

__ds_ns.Tabs = __ds_scope.Tabs;

__ds_ns.TierRow = __ds_scope.TierRow;

__ds_ns.Toast = __ds_scope.Toast;

})();
