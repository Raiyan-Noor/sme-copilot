"use client";

import { useBusiness } from "@/components/business-context";
import { FactNumber, type FactRef } from "@/components/kc/fact";
import { TraceStep } from "@/components/kc/misc";
import { Skeleton } from "@/components/ui/skeleton";
import { api, ApiError } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import { factLabel, money, shortDate } from "@/lib/format";
import type { FactTrace } from "@/lib/types";
import { useApi } from "@/lib/use-api";

/**
 * "Where this number comes from": the fact, the facts it was computed from (each one opens its own trace) and the
 * ledger rows behind it, straight from GET /facts/{id}/explain. Nothing here recomputes a figure.
 */
export function TraceView({ fact }: { fact: FactRef }) {
  const { business, session } = useBusiness();
  const id = business?.id;
  const trace = useApi<FactTrace>(id ? `trace:${session}:${id}:${fact.id}` : null, () =>
    api.explainFact(id as string, fact.id, 25),
  );
  const self = trace.data?.facts.find((f) => f.id === fact.id);
  const inputs = trace.data?.facts.filter((f) => f.id !== fact.id) ?? [];

  return (
    <div className="ka-stack" style={{ gap: 20 }}>
      <div className="ka-trace-sum">
        <span className="kc-label" style={{ color: "var(--text-muted)", fontWeight: 400 }}>
          {factLabel(fact.id)}
        </span>
        <span className="kc-display-number">{fact.display}</span>
        <span className="kc-caption">Computed by {self?.computed_by ?? fact.computed_by ?? "the engine"}</span>
      </div>
      {trace.error !== undefined ? (
        <p className="ka-text" style={{ color: "var(--text-muted)" }}>
          {trace.error instanceof ApiError && trace.error.status === 404
            ? "This figure has no stored trace for today's data. It was computed for that reply only."
            : `Could not load the trace: ${errorMessage(trace.error)}`}
        </p>
      ) : !trace.data ? (
        <Skeleton className="h-40 w-full" />
      ) : (
        <div>
          {inputs.map((f, i) => (
            <TraceStep
              key={f.id}
              op={i === 0 ? "" : "·"}
              label={factLabel(f.id)}
              source={f.computed_by}
              value={<FactNumber fact={f} />}
            />
          ))}
          {trace.data.rows.map((r) => (
            <TraceStep
              key={r.id}
              label={r.text || r.category || r.kind}
              source={[shortDate(r.date), r.category, r.id].filter(Boolean).join(" · ")}
              value={r.amount_minor !== null && r.amount_minor !== undefined ? money(r.amount_minor, r.currency) : ""}
            />
          ))}
          <TraceStep emphasis label="This figure" value={fact.display} />
        </div>
      )}
      {trace.data ? (
        <div className="kc-caption">
          {trace.data.rows_total > trace.data.rows.length
            ? `Showing ${trace.data.rows.length} of ${trace.data.rows_total} source rows. `
            : ""}
          Every figure links back to a bank feed, a document or a setting you chose.
        </div>
      ) : null}
    </div>
  );
}
