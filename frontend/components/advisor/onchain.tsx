"use client";

import { ExternalLink, ShieldCheck } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/kc/button";
import { StatusPill, type PillStatus } from "@/components/kc/status-pill";
import { errorMessage } from "@/lib/errors";
import type { LeafCheck, OnchainCheck } from "@/lib/types";

/**
 * On-chain verification states (invariant 9). Only hashes are anchored, on a testnet; these components show whether
 * what the server holds now still matches the root published on chain, and link to the public block explorer so
 * anyone can check the transaction without trusting this app.
 */

type CheckStatus = LeafCheck["status"] | OnchainCheck["status"];

const STATES: Record<CheckStatus, { pill: PillStatus; label: string }> = {
  match: { pill: "executed", label: "Matches on-chain" },
  mismatch: { pill: "blocked", label: "Does not match" },
  queued: { pill: "waiting", label: "Anchoring" },
  pending: { pill: "waiting", label: "Anchoring" },
  not_anchored: { pill: "neutral", label: "Not anchored yet" },
  unavailable: { pill: "neutral", label: "Chain not reachable" },
};

export function OnchainPill({ status }: { status: CheckStatus }) {
  const s = STATES[status];
  return <StatusPill size="sm" status={s.pill} label={s.label} />;
}

export const shortHash = (h: string | null | undefined, n = 10) => (h ? `${h.slice(0, n)}…` : "");

export function ExplorerLink({ url, label = "View on explorer" }: { url: string | null | undefined; label?: string }) {
  if (!url) return null;
  return (
    <a
      href={url}
      target="_blank"
      rel="noopener noreferrer"
      style={{ display: "inline-flex", alignItems: "center", gap: 4 }}
    >
      {label}
      <ExternalLink size={12} strokeWidth={1.5} aria-hidden />
    </a>
  );
}

/** One line under a pill: what was compared, or why it could not be. */
export function checkCaption(c: LeafCheck): string {
  if (c.status === "match" && c.onchain)
    return `Fingerprint ${shortHash(c.hash)} is in batch ${c.batch_id}, block ${c.onchain.block_number ?? "?"}.`;
  if (c.status === "mismatch")
    return c.reason
      ? `${c.reason[0].toUpperCase()}${c.reason.slice(1)}.`
      : "What is stored now differs from what was anchored.";
  if (c.status === "queued") return "In a batch waiting for the testnet. Check again shortly.";
  if (c.status === "not_anchored") return "Not in an anchored batch yet. Use Anchor now on the Trust screen.";
  return c.reason ? `${c.reason[0].toUpperCase()}${c.reason.slice(1)}.` : "The testnet could not be reached.";
}

/** A "Verify on-chain" button that runs `check` and shows the outcome inline. */
export function VerifyOnchain({ check, compact = false }: { check: () => Promise<LeafCheck>; compact?: boolean }) {
  const [result, setResult] = useState<LeafCheck | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const run = async () => {
    setBusy(true);
    setError(null);
    try {
      setResult(await check());
    } catch (e) {
      setResult(null);
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <span
      style={{
        display: "inline-flex",
        flexDirection: compact ? "row" : "column",
        alignItems: compact ? "center" : "flex-start",
        gap: compact ? 8 : 6,
        flexWrap: "wrap",
      }}
    >
      <span style={{ display: "inline-flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
        <Button variant="ghost" size="sm" iconLeft={ShieldCheck} loading={busy} onClick={run}>
          Verify on-chain
        </Button>
        {result ? <OnchainPill status={result.status} /> : null}
        {result?.onchain?.explorer_url ? <ExplorerLink url={result.onchain.explorer_url} /> : null}
      </span>
      {result && !compact ? <span className="kc-caption">{checkCaption(result)}</span> : null}
      {error ? (
        <span className="kc-caption" style={{ color: "var(--danger)" }} role="alert">
          {error}
        </span>
      ) : null}
    </span>
  );
}
