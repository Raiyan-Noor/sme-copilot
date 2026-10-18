import { Ban, Check, CircleCheck, CircleDashed, Clock, FlaskConical, X, type LucideIcon } from "lucide-react";

import { cn } from "@/lib/utils";

export type PillStatus =
  | "executed"
  | "pending_approval"
  | "denied"
  | "fits"
  | "doesnt_fit"
  | "synthetic"
  | "preview"
  | "not_run";

const STATUS: Record<PillStatus, { label: string; icon: LucideIcon; tone: string }> = {
  executed: { label: "Executed", icon: CircleCheck, tone: "bg-success-soft text-success" },
  pending_approval: { label: "Waiting for approval", icon: Clock, tone: "text-warning ring-1 ring-inset ring-brand-accent-line" },
  denied: { label: "Blocked", icon: Ban, tone: "bg-danger-soft text-danger" },
  fits: { label: "Fits", icon: Check, tone: "bg-success-soft text-success" },
  doesnt_fit: { label: "Doesn't fit", icon: X, tone: "bg-surface-raised text-text-muted" },
  synthetic: { label: "Synthetic data", icon: FlaskConical, tone: "border border-dashed border-border-strong text-text-muted" },
  preview: { label: "Preview data", icon: FlaskConical, tone: "border border-dashed border-border-strong text-text-muted" },
  not_run: { label: "Not run yet", icon: CircleDashed, tone: "bg-surface-raised text-text-muted" },
};

/** Status pill: always icon plus word, never color alone. Status words are fixed by the brand voice. */
export function StatusPill({
  status,
  label,
  size = "md",
  className,
}: {
  status: PillStatus;
  label?: string;
  size?: "sm" | "md";
  className?: string;
}) {
  const s = STATUS[status];
  const Icon = s.icon;
  return (
    <span
      className={cn(
        "inline-flex shrink-0 items-center rounded-full font-medium whitespace-nowrap",
        size === "sm" ? "h-5 gap-1 pr-2 pl-1.5 text-[11px]" : "h-6 gap-1.5 pr-2.5 pl-2 text-xs",
        s.tone,
        className,
      )}
    >
      <Icon className={size === "sm" ? "size-3" : "size-3.5"} strokeWidth={2} aria-hidden />
      <span>{label ?? s.label}</span>
    </span>
  );
}
