import { Ban, Check, CircleCheck, CircleDashed, Clock, FlaskConical, X, type LucideIcon } from "lucide-react";

import { cn } from "@/lib/utils";

export type PillStatus = "executed" | "waiting" | "blocked" | "fits" | "doesnt-fit" | "synthetic" | "neutral";

const STATUS: Record<PillStatus, { label: string; icon: LucideIcon; tone: string }> = {
  executed: { label: "Executed", icon: CircleCheck, tone: "success" },
  waiting: { label: "Waiting for approval", icon: Clock, tone: "warning" },
  blocked: { label: "Blocked", icon: Ban, tone: "danger" },
  fits: { label: "Fits", icon: Check, tone: "success" },
  "doesnt-fit": { label: "Doesn't fit", icon: X, tone: "neutral" },
  synthetic: { label: "Synthetic data", icon: FlaskConical, tone: "synthetic" },
  neutral: { label: "Not run yet", icon: CircleDashed, tone: "neutral" },
};

/** The gateway's three outcomes in the brand's fixed words. */
export function decisionPill(status: "executed" | "pending_approval" | "denied" | "skipped"): PillStatus {
  return status === "executed"
    ? "executed"
    : status === "pending_approval"
      ? "waiting"
      : status === "denied"
        ? "blocked"
        : "neutral";
}

/** Status pill (design/components/badge/StatusPill): always icon plus word, never color alone. */
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
    <span className={cn("kc-pill", `kc-pill--${s.tone}`, `kc-pill--${size}`, className)}>
      <Icon size={size === "sm" ? 12 : 14} strokeWidth={2} aria-hidden />
      <span>{label ?? s.label}</span>
    </span>
  );
}
