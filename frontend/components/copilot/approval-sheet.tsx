"use client";

import { CircleCheck, Clock, PenLine, ShieldAlert } from "lucide-react";

import { Button } from "@/components/ui/button";
import type { PreparedAction } from "@/lib/mock/brief";

import { FactNumber, FactText } from "./fact-number";
import { Sheet } from "./sheet";

/**
 * The approval sheet: everything the owner signs, shown exactly. The signed message is the canonical JSON of
 * `approval.payload` ({action, args_hash, nonce, expiry}); the private key stays in the browser (invariant 6).
 *
 * `onSign` does the browser-side signing (wired with tweetnacl in build prompt 16). Without it the sign button is
 * disabled and says why, so the screen never implies that something was signed.
 */
export function ApprovalSheet({
  action,
  onClose,
  onSign,
  onDecline,
  signing = false,
  signedMandateId,
  error,
}: {
  action: PreparedAction | null;
  onClose: () => void;
  onSign?: () => void;
  onDecline?: () => void;
  signing?: boolean;
  signedMandateId?: number | null;
  error?: string | null;
}) {
  if (!action) return null;
  const { approval } = action;
  const signed = signedMandateId !== undefined && signedMandateId !== null;
  const coolingOff = action.cooling_off_until !== null;
  const canSign = !!onSign && !signing && !coolingOff && !signed;

  const footer = signed ? (
    <Button variant="secondary" onClick={onClose}>
      Done
    </Button>
  ) : (
    <>
      <Button onClick={onSign} disabled={!canSign}>
        <PenLine data-icon="inline-start" strokeWidth={1.5} />
        {signing ? "Signing…" : "Sign and approve"}
      </Button>
      <Button variant="secondary" onClick={onDecline ?? onClose} disabled={signing}>
        {onDecline ? "Decline" : "Not now"}
      </Button>
      {!onSign && (
        <p className="basis-full text-xs text-text-muted">
          Signing with the key on this device is not connected yet, so nothing can be approved here.
        </p>
      )}
    </>
  );

  return (
    <Sheet open onClose={onClose} title={action.title} description="Check every line. You sign exactly this." footer={footer}>
      {signed ? (
        <div className="flex flex-col gap-4" role="status">
          <div className="flex items-center gap-2 text-success">
            <CircleCheck className="size-5" strokeWidth={1.5} aria-hidden />
            <span className="text-[17px] font-medium">Signed</span>
          </div>
          <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-2 text-sm">
            <dt className="text-text-muted">Mandate ID</dt>
            <dd className="font-mono tabular-nums">{signedMandateId}</dd>
            <dt className="text-text-muted">Action</dt>
            <dd className="font-mono">{approval.tool}</dd>
          </dl>
          <p className="text-xs text-text-muted">The signature and its mandate are in the audit log.</p>
        </div>
      ) : (
        <div className="flex flex-col gap-6">
          {action.amount && (
            <div className="flex flex-col gap-1">
              <span className="text-[13px] text-text-muted">Amount</span>
              <span className="text-5xl leading-[56px] font-light tracking-tight">
                <FactNumber fact={action.amount} />
              </span>
              {action.payee && <span className="text-sm">{action.payee}</span>}
            </div>
          )}

          <p className="text-sm leading-[21px] text-pretty">
            <FactText text={action.summary} facts={action.facts} />
          </p>

          {action.risk_flags.length > 0 && (
            <section className="flex flex-col gap-2 rounded-md bg-danger-soft p-4">
              <div className="flex items-center gap-2 text-sm font-medium text-danger">
                <ShieldAlert className="size-4" strokeWidth={1.5} aria-hidden />
                Risk flags
              </div>
              <ul className="list-disc pl-5 text-sm">
                {action.risk_flags.map((r) => (
                  <li key={r}>{r}</li>
                ))}
              </ul>
            </section>
          )}

          {coolingOff && (
            <div className="flex items-center gap-2 rounded-md p-4 text-sm text-warning ring-1 ring-brand-accent-line ring-inset">
              <Clock className="size-4" strokeWidth={1.5} aria-hidden />
              <span>
                First payment to this payee. Signing opens on <FactNumber fact={action.cooling_off_until} />.
              </span>
            </div>
          )}

          {action.details.length > 0 && (
            <section className="flex flex-col">
              <h3 className="mb-1 text-[13px] font-medium text-text-muted">The figures it relies on</h3>
              {action.details.map((d) => (
                <div key={d.label} className="flex items-baseline justify-between gap-3 border-b border-dashed border-border py-3 text-sm">
                  <span>{d.label}</span>
                  <span className="font-medium">
                    <FactNumber fact={d.fact} />
                  </span>
                </div>
              ))}
            </section>
          )}

          <section className="flex flex-col gap-2">
            <h3 className="text-[13px] font-medium text-text-muted">Why it needs you</h3>
            <ul className="flex flex-col gap-1 text-sm">
              {approval.reasons.map((r) => (
                <li key={r}>{r}</li>
              ))}
            </ul>
            {approval.requires_out_of_band_call_script && (
              <p className="text-sm text-warning">Call the payee on a number you already have before you sign.</p>
            )}
          </section>

          <section className="flex flex-col gap-2">
            <h3 className="text-[13px] font-medium text-text-muted">What you sign</h3>
            <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5 rounded-md bg-surface-raised px-4 py-3.5 font-mono text-xs">
              <dt className="text-text-muted">action</dt>
              <dd className="break-all">{approval.payload.action}</dd>
              <dt className="text-text-muted">args_hash</dt>
              <dd className="break-all">{approval.payload.args_hash}</dd>
              <dt className="text-text-muted">nonce</dt>
              <dd className="break-all">{approval.payload.nonce}</dd>
              <dt className="text-text-muted">expiry</dt>
              <dd className="break-all">{approval.payload.expiry}</dd>
            </dl>
          </section>

          {error && <p className="text-sm text-danger">{error}</p>}
        </div>
      )}
    </Sheet>
  );
}
