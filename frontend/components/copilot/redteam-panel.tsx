import { ShieldCheck } from "lucide-react";

import type { AttackOutcome, RedteamResults } from "@/lib/mock/redteam";

import { StatusPill, type PillStatus } from "./status-pill";

const OUTCOME: Record<AttackOutcome, { status: PillStatus; label: string }> = {
  blocked: { status: "executed", label: "Stopped" },
  succeeded: { status: "denied", label: "Got through" },
  not_run: { status: "not_run", label: "Not run yet" },
};

/**
 * Red-team panel on Trust: attacks run vs. stopped, benign tasks completed, and the defense behind each attack.
 * Counts are taken from the results as given; with no run, the tiles say so rather than show a number
 * (invariant 8: never invent results).
 */
export function RedteamPanel({ results }: { results: RedteamResults }) {
  const run = results.attacks.filter((a) => a.outcome !== "not_run");
  const stopped = run.filter((a) => a.outcome === "blocked").length;
  const hasRun = run.length > 0;

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-center gap-2">
        {results.preview && <StatusPill status="preview" size="sm" />}
        <span className="text-xs text-text-muted">
          {hasRun
            ? `Last run ${results.run_on ?? "date unknown"} · ${results.provider ?? "provider unknown"} ${results.model ?? ""}`
            : "The suite has not run yet. Each row shows the defense designed to stop that attack."}
        </span>
      </div>

      <div className="grid grid-cols-1 gap-6 sm:grid-cols-2">
        <Tile label="Attacks stopped" value={hasRun ? `${stopped} of ${run.length}` : "Not run yet"} />
        <Tile
          label="Everyday tasks completed"
          value={results.benign ? `${results.benign.completed} of ${results.benign.total}` : "Not run yet"}
        />
      </div>

      <p className="text-[15px] leading-[22px] text-pretty text-text-muted">
        An attack suite tries to trick the assistant into paying, moving or borrowing money it should not. Each attack
        must be stopped by code, not by the model choosing to refuse.
      </p>

      <ul className="flex flex-col">
        {results.attacks.map((a) => {
          const o = OUTCOME[a.outcome];
          return (
            <li key={a.id} className="flex items-start justify-between gap-4 border-b border-border py-3.5">
              <div className="flex min-w-0 flex-col gap-1">
                <span className="text-sm font-medium">{a.name}</span>
                <span className="text-xs text-text-muted">{a.vector}</span>
                <span className="flex items-center gap-1.5 text-xs text-text-muted">
                  <ShieldCheck className="size-3.5 shrink-0 text-brand-primary" strokeWidth={1.5} aria-hidden />
                  {a.defense}
                </span>
              </div>
              <StatusPill status={o.status} label={o.label} size="sm" />
            </li>
          );
        })}
      </ul>
    </div>
  );
}

function Tile({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-col gap-2">
      <span className="text-[13px] text-text-muted">{label}</span>
      <span className="text-[32px] leading-[1.2] font-light tracking-tight tabular-nums">{value}</span>
    </div>
  );
}
