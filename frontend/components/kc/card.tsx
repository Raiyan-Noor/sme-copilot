import { Coins } from "lucide-react";

import { cn } from "@/lib/utils";

/** Card (design/components/card): default surface step, muted (spacing only), improve (thin gold outline). */
export function Card({
  variant = "default",
  eyebrow,
  title,
  description,
  action,
  footer,
  padding = "md",
  children,
  className,
}: {
  variant?: "default" | "muted" | "improve";
  eyebrow?: React.ReactNode;
  title?: React.ReactNode;
  description?: React.ReactNode;
  action?: React.ReactNode;
  footer?: React.ReactNode;
  padding?: "sm" | "md" | "lg";
  children?: React.ReactNode;
  className?: string;
}) {
  const eb = eyebrow === undefined && variant === "improve" ? "One thing to improve" : eyebrow;
  return (
    <section className={cn("kc-card", `kc-card--${variant}`, `kc-card--pad-${padding}`, className)}>
      {eb || title || action ? (
        <header className="kc-card__head">
          <div className="kc-card__titles">
            {eb ? (
              <div className="kc-card__eyebrow">
                {variant === "improve" ? <Coins size={16} strokeWidth={1.5} aria-hidden /> : null}
                <span>{eb}</span>
              </div>
            ) : null}
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
