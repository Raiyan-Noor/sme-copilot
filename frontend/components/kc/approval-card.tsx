import { PenLine, ShieldCheck } from "lucide-react";

import { cn } from "@/lib/utils";

import { Button } from "./button";
import { StatusPill, type PillStatus } from "./status-pill";

/**
 * ApprovalCard (design/components/approval-card): an action the copilot prepared. The card never signs anything;
 * "Sign and approve" opens the approval sheet, where the owner sees the exact payload (invariant 6).
 */
export function ApprovalCard({
  id,
  title,
  amount,
  description,
  limitNote,
  status,
  meta,
  resolvedNote,
  approveLabel = "Sign and approve",
  onApprove,
  onDecline,
  className,
}: {
  id?: string;
  title: React.ReactNode;
  amount?: React.ReactNode;
  description?: React.ReactNode;
  limitNote?: React.ReactNode;
  status: PillStatus;
  meta?: React.ReactNode;
  resolvedNote?: React.ReactNode;
  approveLabel?: string;
  onApprove?: () => void;
  onDecline?: () => void;
  className?: string;
}) {
  const pending = status === "waiting";
  return (
    <article id={id} className={cn("kc-approval", `kc-approval--${status}`, className)}>
      <div className="kc-approval__top">
        <StatusPill status={status} />
        {meta ? <span className="kc-caption">{meta}</span> : null}
      </div>
      <div className="kc-approval__main">
        <div className="kc-approval__titles">
          <h3 className="kc-section-title">{title}</h3>
          {description ? <p className="kc-approval__desc">{description}</p> : null}
        </div>
        {amount ? <div className="kc-approval__amount">{amount}</div> : null}
      </div>
      {limitNote ? (
        <div className="kc-approval__limit">
          <ShieldCheck size={16} strokeWidth={1.5} aria-hidden />
          <span>{limitNote}</span>
        </div>
      ) : null}
      {pending && onApprove ? (
        <div className="kc-approval__actions">
          <Button variant="primary" iconLeft={PenLine} onClick={onApprove}>
            {approveLabel}
          </Button>
          {onDecline ? (
            <Button variant="secondary" onClick={onDecline}>
              Decline
            </Button>
          ) : null}
        </div>
      ) : resolvedNote ? (
        <div className="kc-caption">{resolvedNote}</div>
      ) : null}
    </article>
  );
}
