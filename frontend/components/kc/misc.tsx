"use client";

import { Ban, CircleCheck, Coins, Info, PenLine, X, Zap, type LucideIcon } from "lucide-react";

import { cn } from "@/lib/utils";

import { Button } from "./button";

/** Progress (design/components/progress). */
export function Progress({
  value,
  max = 100,
  tone = "brand",
  size = "md",
  label,
}: {
  value: number;
  max?: number;
  tone?: "brand" | "teal" | "gold" | "danger" | "neutral";
  size?: "sm" | "md";
  label?: string;
}) {
  const p = max > 0 ? Math.max(0, Math.min(100, (value / max) * 100)) : 0;
  return (
    <div
      className={cn("kc-progress", `kc-progress--${size}`)}
      role="progressbar"
      aria-valuemin={0}
      aria-valuemax={max}
      aria-valuenow={value}
      aria-label={label}
    >
      <div className={cn("kc-progress__fill", `kc-progress__fill--${tone}`)} style={{ width: `${p}%` }} />
    </div>
  );
}

/** FactorBar (design/components/progress/FactorBar): a labelled bar with its value on the right. */
export function FactorBar({
  label,
  value,
  max = 100,
  valueLabel,
  hint,
  tone = "brand",
}: {
  label: React.ReactNode;
  value: number;
  max?: number;
  valueLabel?: React.ReactNode;
  hint?: React.ReactNode;
  tone?: "brand" | "teal" | "gold" | "danger" | "neutral";
}) {
  return (
    <div className="kc-factor">
      <div className="kc-factor__row">
        <span className="kc-factor__label">{label}</span>
        <span className="kc-factor__value">{valueLabel}</span>
      </div>
      <div className="kc-factor__track-wrap">
        <Progress value={value} max={max} tone={tone} size="sm" label={typeof label === "string" ? label : undefined} />
      </div>
      {hint ? <div className="kc-caption">{hint}</div> : null}
    </div>
  );
}

/** Tabs (design/components/tabs): underline tabs with optional counts and arrow-key movement. */
export function Tabs<T extends string>({
  items,
  value,
  onValueChange,
  size = "md",
}: {
  items: { value: T; label: string; count?: number }[];
  value: T;
  onValueChange: (v: T) => void;
  size?: "sm" | "md";
}) {
  const onKey = (e: React.KeyboardEvent<HTMLButtonElement>, i: number) => {
    if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
    const n = (i + (e.key === "ArrowRight" ? 1 : -1) + items.length) % items.length;
    onValueChange(items[n].value);
    const btns = e.currentTarget.parentElement?.querySelectorAll<HTMLButtonElement>("[role=tab]");
    btns?.[n]?.focus();
  };
  return (
    <div role="tablist" className={cn("kc-tabs", `kc-tabs--${size}`)}>
      {items.map((t, i) => {
        const on = t.value === value;
        return (
          <button
            key={t.value}
            type="button"
            role="tab"
            aria-selected={on}
            tabIndex={on ? 0 : -1}
            className={cn("kc-tabs__tab", on && "is-active")}
            onClick={() => onValueChange(t.value)}
            onKeyDown={(e) => onKey(e, i)}
          >
            <span>{t.label}</span>
            {t.count !== undefined ? <span className="kc-tabs__count">{t.count}</span> : null}
          </button>
        );
      })}
    </div>
  );
}

export type Column<R> = {
  key: string;
  header: React.ReactNode;
  align?: "left" | "right";
  width?: number;
  render: (row: R) => React.ReactNode;
};

/** Table (design/components/table): right-aligned tabular money, clickable rows. */
export function Table<R>({
  columns,
  rows,
  rowKey,
  onRowClick,
  density = "regular",
  empty = "Nothing here yet.",
}: {
  columns: Column<R>[];
  rows: R[];
  rowKey: (row: R) => string;
  onRowClick?: (row: R) => void;
  density?: "regular" | "compact";
  empty?: React.ReactNode;
}) {
  return (
    <div className="kc-table-wrap">
      <table className={cn("kc-table", `kc-table--${density}`)}>
        <thead>
          <tr>
            {columns.map((c) => (
              <th key={c.key} style={{ textAlign: c.align ?? "left", width: c.width }}>
                {c.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 ? (
            <tr>
              <td colSpan={columns.length} className="kc-table__empty">
                {empty}
              </td>
            </tr>
          ) : (
            rows.map((r) => (
              <tr
                key={rowKey(r)}
                onClick={onRowClick ? () => onRowClick(r) : undefined}
                className={onRowClick ? "kc-table__row--click" : undefined}
              >
                {columns.map((c) => (
                  <td
                    key={c.key}
                    style={{ textAlign: c.align ?? "left" }}
                    className={c.align === "right" ? "kc-table__num" : undefined}
                  >
                    {c.render(r)}
                  </td>
                ))}
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  );
}

const TIER_MODES = {
  auto: { label: "Acts on its own", icon: Zap },
  approval: { label: "Asks first", icon: PenLine },
  never: { label: "Never", icon: Ban },
} satisfies Record<string, { label: string; icon: LucideIcon }>;

/** TierRow (design/components/tier-row): one signed permission tier with its tools and limit. */
export function TierRow({
  tier,
  name,
  description,
  mode,
  limit,
  tools,
  signedNote,
  onEdit,
  editLabel = "Change limit",
}: {
  tier: number;
  name: string;
  description?: React.ReactNode;
  mode: keyof typeof TIER_MODES;
  limit?: React.ReactNode;
  tools: string[];
  signedNote?: React.ReactNode;
  onEdit?: () => void;
  editLabel?: string;
}) {
  const m = TIER_MODES[mode];
  const ModeIcon = m.icon;
  return (
    <div className={cn("kc-tier", `kc-tier--${mode}`)}>
      <div className="kc-tier__num" aria-label={`Tier ${tier}`}>
        {tier}
      </div>
      <div className="kc-tier__main">
        <div className="kc-tier__head">
          <span className="kc-tier__name">{name}</span>
          <span className={cn("kc-tier__mode", `kc-tier__mode--${mode}`)}>
            <ModeIcon size={14} strokeWidth={2} aria-hidden />
            {m.label}
          </span>
        </div>
        {description ? <p className="kc-tier__desc">{description}</p> : null}
        {tools.length ? (
          <ul className="kc-tier__tools" aria-label="Tools">
            {tools.map((t) => (
              <li key={t} className="kc-tier__tool">
                {t}
              </li>
            ))}
          </ul>
        ) : null}
        {signedNote ? <div className="kc-caption kc-tier__signed">{signedNote}</div> : null}
      </div>
      <div className="kc-tier__side">
        {limit ? (
          <div className="kc-tier__limit">
            <span className="kc-caption">Limit</span>
            <span className="kc-tier__limit-val">{limit}</span>
          </div>
        ) : null}
        {onEdit ? (
          <Button variant="ghost" size="sm" onClick={onEdit}>
            {editLabel}
          </Button>
        ) : null}
      </div>
    </div>
  );
}

const TOAST_ICONS: Record<string, LucideIcon> = { default: Info, success: CircleCheck, danger: Ban, savings: Coins };

export type ToastData = {
  variant?: "default" | "success" | "danger" | "savings";
  title: string;
  description?: React.ReactNode;
};

/** Toast (design/components/toast): past tense, factual. */
export function Toast({ variant = "default", title, description, onClose }: ToastData & { onClose?: () => void }) {
  const Icon = TOAST_ICONS[variant];
  return (
    <div role="status" aria-live="polite" className={cn("kc-toast", `kc-toast--${variant}`)}>
      <span className="kc-toast__icon">
        <Icon size={20} strokeWidth={1.5} aria-hidden />
      </span>
      <div className="kc-toast__content">
        <div className="kc-toast__title">{title}</div>
        {description ? <div className="kc-toast__desc">{description}</div> : null}
      </div>
      {onClose ? (
        <button type="button" className="kc-toast__close" aria-label="Close" onClick={onClose}>
          <X size={16} strokeWidth={1.5} />
        </button>
      ) : null}
    </div>
  );
}

/** TraceStep (design/components/sheet/TraceStep): one row of the trace drawer. */
export function TraceStep({
  label,
  value,
  source,
  op,
  emphasis = false,
}: {
  label: React.ReactNode;
  value: React.ReactNode;
  source?: React.ReactNode;
  op?: string;
  emphasis?: boolean;
}) {
  return (
    <div className={cn("kc-trace", emphasis && "kc-trace--total")}>
      <span className="kc-trace__op">{op ?? ""}</span>
      <div className="kc-trace__main">
        <div className="kc-trace__label">{label}</div>
        {source ? <div className="kc-trace__source">{source}</div> : null}
      </div>
      <span className="kc-trace__value">{value}</span>
    </div>
  );
}
