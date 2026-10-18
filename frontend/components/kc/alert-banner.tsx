import { Info, ShieldAlert, X } from "lucide-react";

import { cn } from "@/lib/utils";

/** AlertBanner (design/components/alert-banner): fraud or info, with optional actions. */
export function AlertBanner({
  variant = "info",
  title,
  children,
  actions,
  onDismiss,
  eyebrow,
  className,
}: {
  variant?: "fraud" | "info";
  title?: React.ReactNode;
  children?: React.ReactNode;
  actions?: React.ReactNode;
  onDismiss?: () => void;
  eyebrow?: React.ReactNode;
  className?: string;
}) {
  const eb = eyebrow === undefined ? (variant === "fraud" ? "Possible fraud" : "Note") : eyebrow;
  const Icon = variant === "fraud" ? ShieldAlert : Info;
  return (
    <div role={variant === "fraud" ? "alert" : "status"} className={cn("kc-alert", `kc-alert--${variant}`, className)}>
      <span className="kc-alert__icon">
        <Icon size={20} strokeWidth={1.5} aria-hidden />
      </span>
      <div className="kc-alert__content">
        {eb ? <div className="kc-alert__eyebrow">{eb}</div> : null}
        {title ? <div className="kc-alert__title">{title}</div> : null}
        {children ? <div className="kc-alert__body">{children}</div> : null}
        {actions ? <div className="kc-alert__actions">{actions}</div> : null}
      </div>
      {onDismiss ? (
        <button type="button" className="kc-alert__close" onClick={onDismiss} aria-label="Dismiss">
          <X size={18} strokeWidth={1.5} />
        </button>
      ) : null}
    </div>
  );
}
