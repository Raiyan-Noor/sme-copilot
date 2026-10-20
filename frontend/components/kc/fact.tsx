"use client";

import { createContext, Fragment, useContext } from "react";

import type { Fact, ReplySegment } from "@/lib/types";
import { cn } from "@/lib/utils";

/** The least the UI needs to show a figure and open its trace: the Fact's ID and its code-rendered display. */
export type FactRef = Pick<Fact, "id" | "display"> & Partial<Pick<Fact, "computed_by" | "unit" | "value">>;

const TraceContext = createContext<(fact: FactRef) => void>(() => {});

/** Sets what clicking a FactNumber does below it: the shell opens the trace in the detail panel; the approval
 * sheet shows it inside the sheet, so the owner never loses what they are about to sign. */
export const TraceScope = TraceContext.Provider;

export function useTrace(): (fact: FactRef) => void {
  return useContext(TraceContext);
}

/**
 * A figure on screen (design/components/fact-number). Numbers shown to the owner only ever come from a Fact
 * computed in code (invariant 4); clicking one opens "Where this number comes from".
 */
export function FactNumber({
  fact,
  tone = "default",
  className,
}: {
  fact: FactRef | null | undefined;
  tone?: "default" | "positive" | "negative";
  className?: string;
}) {
  const open = useTrace();
  if (!fact) return <span className="kc-caption">n/a</span>;
  return (
    <button
      type="button"
      onClick={() => open(fact)}
      className={cn("kc-fact", `kc-fact--${tone}`, className)}
      title="Show where this number comes from"
    >
      {fact.display}
    </button>
  );
}

const PLACEHOLDER = /\{fact:([^}]+)\}/g;
const BOLD = /\*\*([^*]+)\*\*/g;

function renderPlaceholders(text: string, facts: Record<string, Fact>, keyBase: string) {
  const parts = text.split(PLACEHOLDER);
  return parts.map((part, i) =>
    i % 2 === 0 ? (
      <Fragment key={`${keyBase}-${i}`}>{part}</Fragment>
    ) : facts[part] ? (
      <FactNumber key={`${keyBase}-${i}`} fact={facts[part]} />
    ) : (
      <span key={`${keyBase}-${i}`} className="kc-caption" title={`Unknown figure ${part}`}>
        [missing figure]
      </span>
    ),
  );
}

/**
 * Text with `{fact:id}` placeholders and `**bold**` markers, as the brief writer and the gateway return it,
 * rendered with each placeholder as a FactNumber and each bold span as <strong>. An unknown fact ID shows a
 * visible gap, never a guessed number (invariant 4).
 */
export function FactText({ text, facts }: { text: string; facts: Record<string, Fact> }) {
  const segments = text.split(BOLD);
  return (
    <>
      {segments.map((seg, i) =>
        i % 2 === 1 ? (
          <strong key={i}>{renderPlaceholders(seg, facts, `b${i}`)}</strong>
        ) : (
          <Fragment key={i}>{renderPlaceholders(seg, facts, `p${i}`)}</Fragment>
        ),
      )}
    </>
  );
}

/** A reply that already passed the Numeric Firewall: plain text segments, and fact segments that open a trace. */
export function Segments({ segments }: { segments: ReplySegment[] }) {
  return (
    <>
      {segments.map((s, i) =>
        s.fact_id ? (
          <FactNumber key={i} fact={{ id: s.fact_id, display: s.text }} />
        ) : (
          <Fragment key={i}>{s.text}</Fragment>
        ),
      )}
    </>
  );
}

/** KpiTile (design/components/kpi-tile): a big tabular figure that opens its trace. */
export function KpiTile({
  label,
  fact,
  caption,
  size = "lg",
}: {
  label: React.ReactNode;
  fact: FactRef | null | undefined;
  caption?: React.ReactNode;
  size?: "lg" | "md";
}) {
  return (
    <div className={cn("kc-kpi", `kc-kpi--${size}`)}>
      <div className="kc-kpi__label">
        <span>{label}</span>
      </div>
      <div className="kc-kpi__value">
        <FactNumber fact={fact} />
      </div>
      {caption ? (
        <div className="kc-kpi__foot">
          <span className="kc-caption">{caption}</span>
        </div>
      ) : null}
    </div>
  );
}
