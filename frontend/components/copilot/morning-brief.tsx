"use client";

import { ChevronRight, CircleCheck, Coins, PenLine, ShieldAlert } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { Logo } from "@/components/brand/Logo";
import { Button } from "@/components/ui/button";
import type { BriefAlert, MorningBrief, PreparedAction } from "@/lib/mock/brief";
import { cn } from "@/lib/utils";

import { ApprovalCard } from "./approval-card";
import { ApprovalSheet } from "./approval-sheet";
import { FactNumber, FactText } from "./fact-number";
import { StatusPill } from "./status-pill";

/**
 * The Morning Brief: the day opens as the advisor's first message, with what needs the owner attached to it.
 * Prose arrives with {fact:id} placeholders and every figure renders as a traceable FactNumber (invariant 4).
 */
export function MorningBriefMessage({ brief }: { brief: MorningBrief }) {
  const [open, setOpen] = useState<PreparedAction | null>(null);

  return (
    <div className="flex items-start gap-3.5">
      <div className="mt-1 flex size-7 shrink-0 items-center justify-center" aria-hidden>
        <Logo variant="mark" className="h-auto w-[26px]" />
      </div>
      <div className="flex min-w-0 flex-1 flex-col gap-1.5">
        <div className="flex flex-wrap items-center gap-2 text-xs text-text-muted">
          <span>Morning brief · {brief.as_of.display}</span>
          {brief.preview && <StatusPill status="preview" size="sm" />}
        </div>
        <div className="flex flex-col gap-3 font-advisor text-[19px] leading-[30px] text-pretty">
          {brief.paragraphs.map((p, i) => (
            <p key={i}>
              <FactText text={p} facts={brief.facts} />
            </p>
          ))}
        </div>

        <div className="mt-4 flex flex-col gap-4">
          {brief.alerts.map((a) => (
            <FraudAlert key={a.id} alert={a} />
          ))}
          {brief.needs_you.map((action) => (
            <ApprovalCard key={action.approval.approval_id} action={action} onOpen={() => setOpen(action)} />
          ))}
          {brief.improve && (
            <section className="flex flex-col gap-4 rounded-lg bg-surface-muted p-6 ring-1 ring-brand-accent-line ring-inset">
              <div className="flex items-start justify-between gap-4">
                <div className="flex min-w-0 flex-col gap-1">
                  <span className="text-[13px] text-brand-accent">One thing to improve</span>
                  <h3 className="text-[17px] leading-6 font-medium">{brief.improve.title}</h3>
                </div>
                <span className="inline-flex h-[22px] shrink-0 items-center gap-1 rounded-sm bg-success-soft px-2 text-xs font-medium text-success">
                  <Coins className="size-3.5" strokeWidth={1.5} aria-hidden />
                  Saves <FactNumber fact={brief.improve.yearly_saving} /> a year
                </span>
              </div>
              <p className="text-[15px] leading-[22px] text-pretty">
                <FactText text={brief.improve.text} facts={brief.improve.facts} />
              </p>
              {brief.improve.action && (
                <div>
                  <Button variant="secondary" size="sm" onClick={() => setOpen(brief.improve!.action)}>
                    <PenLine data-icon="inline-start" strokeWidth={1.5} />
                    Prepare cancellation
                  </Button>
                </div>
              )}
            </section>
          )}
          <Overnight brief={brief} />
          {brief.coming_up.length > 0 && (
            <section className="flex flex-col">
              <h3 className="mb-1 text-[13px] font-medium text-text-muted">Coming up</h3>
              {brief.coming_up.map((c) => (
                <div key={c.id} className="flex items-baseline justify-between gap-3 border-b border-border py-2.5 text-sm">
                  <span className="min-w-0">
                    {c.label}
                    <span className="ml-2 text-xs text-text-muted">
                      <FactNumber fact={c.due} />
                    </span>
                  </span>
                  <FactNumber fact={c.amount} />
                </div>
              ))}
            </section>
          )}
        </div>
      </div>

      <ApprovalSheet action={open} onClose={() => setOpen(null)} />
    </div>
  );
}

function FraudAlert({ alert }: { alert: BriefAlert }) {
  return (
    <div role="alert" className="flex items-start gap-3.5 rounded-lg bg-danger-soft px-5 py-[18px]">
      <ShieldAlert className="mt-0.5 size-5 shrink-0 text-danger" strokeWidth={1.5} aria-hidden />
      <div className="flex min-w-0 flex-1 flex-col gap-1">
        <span className="text-xs font-medium text-danger">Possible fraud</span>
        <span className="text-[15px] leading-[22px] font-medium">{alert.title}</span>
        <p className="text-sm leading-[21px] text-pretty">
          <FactText text={alert.body} facts={alert.facts} />
        </p>
        {alert.risk_flags.length > 0 && (
          <ul className="mt-1 flex flex-wrap gap-1.5">
            {alert.risk_flags.map((r) => (
              <li key={r} className="rounded-full bg-surface-muted px-2.5 py-0.5 text-xs text-text">
                {r}
              </li>
            ))}
          </ul>
        )}
        <div className="mt-3">
          <Button variant="secondary" size="sm" render={<Link href="/inbox" />} nativeButton={false}>
            Review the email
          </Button>
        </div>
      </div>
    </div>
  );
}

function Overnight({ brief }: { brief: MorningBrief }) {
  const [open, setOpen] = useState(false);
  const items = brief.done_overnight;
  if (items.length === 0) return null;
  const executed = items.filter((i) => i.status === "executed").length;
  return (
    <div>
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center gap-2.5 rounded-md py-2 text-left text-sm hover:text-text"
      >
        <CircleCheck className="size-[18px] text-success" strokeWidth={1.5} aria-hidden />
        <span>{executed === items.length ? "Handled overnight within your signed limits" : "Overnight, within your signed limits"}</span>
        <ChevronRight
          className={cn("ml-auto size-4 text-text-muted transition-transform", open && "rotate-90")}
          strokeWidth={1.5}
          aria-hidden
        />
      </button>
      {open && (
        <ul className="flex flex-col">
          {items.map((o, i) => (
            <li key={i} className="flex items-center justify-between gap-3 border-b border-border py-2.5 pl-7">
              <span className="flex min-w-0 flex-col">
                <span className="text-sm">{o.summary}</span>
                <span className="text-xs text-text-muted">
                  <span className="font-mono">{o.tool}</span> · <FactNumber fact={o.date} />
                </span>
              </span>
              <StatusPill status={o.status} size="sm" />
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
