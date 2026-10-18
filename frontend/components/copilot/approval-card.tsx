"use client";

import { PenLine, ShieldCheck } from "lucide-react";

import { Button } from "@/components/ui/button";
import type { PreparedAction } from "@/lib/mock/brief";
import { cn } from "@/lib/utils";

import { FactNumber, FactText } from "./fact-number";
import { StatusPill, type PillStatus } from "./status-pill";

function pillStatus(status: string): PillStatus {
  if (status === "executed" || status === "denied") return status;
  return "pending_approval";
}

/**
 * An action the copilot prepared that needs the owner's signature. Opening it shows the approval sheet; the card
 * itself never signs anything (invariant 6: signing happens in the sheet, in the browser).
 */
export function ApprovalCard({
  action,
  onOpen,
  onDecline,
  className,
}: {
  action: PreparedAction;
  onOpen: () => void;
  onDecline?: () => void;
  className?: string;
}) {
  const status = pillStatus(action.approval.status);
  const waiting = status === "pending_approval";
  return (
    <article
      className={cn(
        "flex min-w-0 flex-col gap-5 rounded-lg bg-surface-muted p-6 text-text",
        waiting && "ring-1 ring-brand-accent-line ring-inset",
        status === "denied" && "ring-1 ring-danger/40 ring-inset",
        className,
      )}
    >
      <div className="flex items-center justify-between gap-3">
        <StatusPill status={status} />
        <span className="font-mono text-xs text-text-muted">{action.approval.tool}</span>
      </div>
      <div className="flex items-start justify-between gap-4">
        <div className="flex min-w-0 flex-col gap-1.5">
          <h3 className="text-[17px] leading-6 font-medium">{action.title}</h3>
          <p className="text-sm leading-[21px] text-pretty text-text-muted">
            <FactText text={action.summary} facts={action.facts} />
          </p>
        </div>
        {action.amount && (
          <div className="text-[30px] leading-9 font-light tracking-tight whitespace-nowrap">
            <FactNumber fact={action.amount} />
          </div>
        )}
      </div>
      {action.details.length > 0 && (
        <dl className="grid grid-cols-[repeat(auto-fit,minmax(120px,1fr))] gap-3 rounded-md bg-surface-raised px-4 py-3.5">
          {action.details.map((d) => (
            <div key={d.label}>
              <dt className="text-xs text-text-muted">{d.label}</dt>
              <dd className="mt-0.5 text-sm font-medium">
                <FactNumber fact={d.fact} />
              </dd>
            </div>
          ))}
        </dl>
      )}
      <div className="flex items-center gap-2 text-[13px] text-text-muted">
        <ShieldCheck className="size-4 text-brand-primary" strokeWidth={1.5} aria-hidden />
        <span>
          <FactText text={action.limit_note} facts={action.facts} />
        </span>
      </div>
      {waiting && (
        <div className="flex flex-wrap gap-2">
          <Button onClick={onOpen}>
            <PenLine data-icon="inline-start" strokeWidth={1.5} />
            Review and sign
          </Button>
          {onDecline && (
            <Button variant="secondary" onClick={onDecline}>
              Decline
            </Button>
          )}
        </div>
      )}
    </article>
  );
}
