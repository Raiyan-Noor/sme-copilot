"use client";

import { createContext, Fragment, useCallback, useContext, useState } from "react";

import { useBusiness } from "@/components/business-context";
import { errorMessage } from "@/components/data";
import { Skeleton } from "@/components/ui/skeleton";
import { api } from "@/lib/api";
import type { Fact, FactTrace, SourceRow } from "@/lib/types";
import { useApi } from "@/lib/use-api";
import { cn } from "@/lib/utils";

import { Sheet } from "./sheet";

/** Facts with this `computed_by` are preview data (lib/mock); they have no trace in the API. */
export const PREVIEW_COMPUTED_BY = "preview";

const TraceContext = createContext<(fact: Fact) => void>(() => {});

/** Holds the "Where this number comes from" drawer that every FactNumber below it opens. */
export function FactTraceProvider({ children }: { children: React.ReactNode }) {
  const [fact, setFact] = useState<Fact | null>(null);
  const close = useCallback(() => setFact(null), []);
  return (
    <TraceContext.Provider value={setFact}>
      {children}
      <Sheet
        open={fact !== null}
        onClose={close}
        title="Where this number comes from"
        description={fact ? `${fact.id} · ${fact.computed_by}` : undefined}
      >
        {fact && <TraceBody fact={fact} />}
      </Sheet>
    </TraceContext.Provider>
  );
}

/**
 * A figure on screen. Numbers shown to the owner only ever come from a Fact computed in code (invariant 4);
 * clicking one opens its trace back to the source rows.
 */
export function FactNumber({ fact, className }: { fact: Fact | null | undefined; className?: string }) {
  const open = useContext(TraceContext);
  if (!fact) return <span className="text-text-muted">n/a</span>;
  return (
    <button
      type="button"
      onClick={() => open(fact)}
      className={cn(
        "-mx-0.5 cursor-pointer rounded-[4px] px-0.5 tabular-nums underline decoration-border-strong decoration-dotted decoration-1 underline-offset-[0.22em] transition-colors hover:bg-brand-primary-soft hover:decoration-brand-primary",
        className,
      )}
    >
      {fact.display}
    </button>
  );
}

const PLACEHOLDER = /\{fact:([^}]+)\}/g;

/**
 * Renders text with `{fact:id}` placeholders as clickable FactNumbers. An unknown ID renders as a visible gap,
 * never as a guessed number.
 */
export function FactText({ text, facts }: { text: string; facts: Record<string, Fact> }) {
  const parts = text.split(PLACEHOLDER);
  return (
    <>
      {parts.map((part, i) =>
        i % 2 === 0 ? (
          <Fragment key={i}>{part}</Fragment>
        ) : facts[part] ? (
          <FactNumber key={i} fact={facts[part]} />
        ) : (
          <span key={i} className="text-text-muted" title={`Unknown fact ${part}`}>
            [missing figure]
          </span>
        ),
      )}
    </>
  );
}

function TraceBody({ fact }: { fact: Fact }) {
  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-col gap-1">
        <span className="text-[56px] leading-[1.1] font-light tracking-tight tabular-nums">{fact.display}</span>
        <span className="text-xs text-text-muted">Computed by {fact.computed_by}</span>
      </div>
      {fact.computed_by === PREVIEW_COMPUTED_BY ? (
        <p className="text-sm text-text-muted">
          This is a preview figure. Its trace appears when the endpoint that computes it is live.
        </p>
      ) : (
        <LiveTrace fact={fact} />
      )}
    </div>
  );
}

function LiveTrace({ fact }: { fact: Fact }) {
  const { business, session } = useBusiness();
  const id = business?.id;
  const trace = useApi<FactTrace>(id ? `trace:${session}:${id}:${fact.id}` : null, () =>
    api.explainFact(id as string, fact.id, 25),
  );
  if (trace.error !== undefined) {
    return <p className="text-sm text-danger">Could not load the trace: {errorMessage(trace.error)}</p>;
  }
  if (!trace.data) return <Skeleton className="h-40 w-full" />;
  const inputs = trace.data.facts.filter((f) => f.id !== fact.id);
  return (
    <>
      {inputs.length > 0 && (
        <section className="flex flex-col">
          <h3 className="mb-1 text-[13px] font-medium text-text-muted">Computed from</h3>
          {inputs.map((f) => (
            <div key={f.id} className="flex items-baseline justify-between gap-3 border-b border-dashed border-border py-3">
              <div className="min-w-0">
                <div className="truncate text-sm">{f.id}</div>
                <div className="text-xs text-text-muted">{f.computed_by}</div>
              </div>
              <span className="text-sm font-medium whitespace-nowrap tabular-nums">{f.display}</span>
            </div>
          ))}
        </section>
      )}
      <section className="flex flex-col">
        <h3 className="mb-1 text-[13px] font-medium text-text-muted">
          Source rows ({trace.data.rows.length} of {trace.data.rows_total})
        </h3>
        {trace.data.rows.map((r) => (
          <SourceRowLine key={r.id} row={r} />
        ))}
        {trace.data.rows.length === 0 && <p className="text-sm text-text-muted">No source rows: a setting or the clock.</p>}
      </section>
    </>
  );
}

function money(minor: number, currency: string | null | undefined): string {
  return new Intl.NumberFormat("en-US", { style: "currency", currency: currency || "USD" }).format(minor / 100);
}

function SourceRowLine({ row }: { row: SourceRow }) {
  return (
    <div className="flex items-baseline justify-between gap-3 border-b border-border py-2.5">
      <div className="min-w-0">
        <div className="truncate text-sm">{row.text || row.category || row.kind}</div>
        <div className="text-xs text-text-muted tabular-nums">
          {row.date} · {row.id}
        </div>
      </div>
      {row.amount_minor !== null && row.amount_minor !== undefined && (
        <span className="text-sm whitespace-nowrap tabular-nums">{money(row.amount_minor, row.currency)}</span>
      )}
    </div>
  );
}
