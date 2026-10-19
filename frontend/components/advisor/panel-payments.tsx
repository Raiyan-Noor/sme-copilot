"use client";

import {
  Banknote,
  Check,
  ExternalLink,
  LogOut,
  PenLine,
  Phone,
  Plus,
  RefreshCw,
  ShieldAlert,
  UserPlus,
  X,
} from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

import { useBusinessKey } from "@/components/business-context";
import { Badge } from "@/components/kc/badge";
import { Button } from "@/components/kc/button";
import { Table } from "@/components/kc/misc";
import { StatusPill, type PillStatus } from "@/components/kc/status-pill";
import { Skeleton } from "@/components/ui/skeleton";
import { APP_NAME } from "@/config/app";
import { API_URL, api } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import { flagLabel, money, reasonLabel, ruleLabel, shortDate } from "@/lib/format";
import type {
  Flag,
  PaymentConnectionStatus,
  PaymentsOverview,
  PaymentView,
  SuggestedPayment,
} from "@/lib/types";
import { useApi } from "@/lib/use-api";

import { PanelFrame } from "./detail-panel";
import { VerifyOnchain } from "./onchain";
import { useAdvisor } from "./state";

type Status = PaymentView["status"];

const STATUS: Record<Status, { pill: PillStatus; label: string }> = {
  proposed: { pill: "neutral", label: "Proposed" },
  awaiting_approval: { pill: "waiting", label: "Waiting for you" },
  approved: { pill: "executed", label: "Approved" },
  sent: { pill: "waiting", label: "Sent, processing" },
  settled: { pill: "executed", label: "Settled" },
  failed: { pill: "blocked", label: "Failed" },
  denied: { pill: "blocked", label: "Refused" },
  cancelled: { pill: "doesnt-fit", label: "Cancelled" },
};

const STEPS: Status[] = ["proposed", "approved", "sent", "settled"];
const POPUP = "width=520,height=720,menubar=no,toolbar=no";
const FIRST = 5;

function PaymentPill({ status }: { status: Status }) {
  const s = STATUS[status];
  return <StatusPill size="sm" status={s.pill} label={s.label} />;
}

/** proposed → approved → sent → settled, as dots; the next one turns red if it failed, was refused or cancelled. */
function Steps({ p }: { p: PaymentView }) {
  const reached = [...(p.events ?? []).map((e) => e.status), p.status];
  const last = Math.max(...reached.map((s) => STEPS.indexOf(s)), reached.includes("sent") ? 2 : 0);
  const bad = p.status === "failed" || p.status === "denied" || p.status === "cancelled";
  return (
    <span className="ka-live__steps" aria-label={`Status: ${STATUS[p.status].label}`}>
      {STEPS.map((s, i) => (
        <span key={s} className={`ka-live__step${i <= last ? " is-done" : bad && i === last + 1 ? " is-bad" : ""}`} />
      ))}
    </span>
  );
}

/** An event's note: a gateway code becomes words; the provider's own notes are already words. */
function noteLabel(note: string | null | undefined): string {
  if (!note) return "";
  if (note.startsWith("tier_") || note.startsWith("untrusted_provenance:")) return reasonLabel(note);
  return /\s/.test(note) ? note : ruleLabel(note);
}

/** Keep the last loaded data on screen while a live event reloads it, so rows update instead of flashing. */
function useSticky<T>(value: T | undefined): T | undefined {
  const [last, setLast] = useState<T | undefined>(value);
  if (value !== undefined && value !== last) setLast(value);
  return value ?? last;
}

function useConnect(businessId: string, onDone: () => void) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const watch = useRef<number | null>(null);

  const stop = useCallback(() => {
    if (watch.current !== null) window.clearInterval(watch.current);
    watch.current = null;
    setBusy(false);
  }, []);

  useEffect(() => {
    const origin = new URL(API_URL).origin;
    const onMessage = (e: MessageEvent) => {
      if (e.origin !== origin || e.data?.type !== "payments-connection") return;
      stop();
      if (!e.data.ok) setError("The payment service was not connected. Please try again.");
      onDone();
    };
    window.addEventListener("message", onMessage);
    return () => {
      window.removeEventListener("message", onMessage);
      if (watch.current !== null) window.clearInterval(watch.current);
    };
  }, [onDone, stop]);

  const connect = async () => {
    setError(null);
    const popup = window.open("", "payments-connect", POPUP); // inside the click, so it is not blocked
    setBusy(true);
    try {
      const { authorize_url } = await api.paymentConnect(businessId, { client_name: APP_NAME });
      if (popup) popup.location.href = authorize_url;
      else window.location.href = authorize_url;
    } catch (e) {
      popup?.close();
      setBusy(false);
      setError(errorMessage(e));
      return;
    }
    watch.current = window.setInterval(async () => {
      const s = await api.paymentConnection(businessId).catch(() => null);
      if (s?.state === "connected" || !popup || popup.closed) {
        stop();
        onDone();
      }
    }, 1500);
  };
  return { connect, busy, error };
}

function ConnectionCard({ status, businessId, reload }: {
  status: PaymentConnectionStatus;
  businessId: string;
  reload: () => void;
}) {
  const { toast } = useAdvisor();
  const { connect, busy, error } = useConnect(businessId, reload);
  const [asking, setAsking] = useState(false);
  const [leaving, setLeaving] = useState(false);
  const connected = status.state === "connected";
  const c = status.currency;

  const disconnect = async () => {
    setLeaving(true);
    try {
      await api.paymentDisconnect(businessId);
      toast({ title: "Payment service disconnected", description: "Its access was revoked at the provider." });
      reload();
    } catch (e) {
      toast({ variant: "danger", title: "Could not disconnect", description: errorMessage(e) });
    } finally {
      setLeaving(false);
    }
  };

  return (
    <section className="ka-gmail" aria-label="Connected payment service">
      <div className="ka-gmail__head">
        <Banknote size={20} strokeWidth={1.5} aria-hidden style={{ color: "var(--brand-primary)" }} />
        <div style={{ flex: 1, minWidth: 0 }}>
          <div className="kc-label">{status.provider} (simulated)</div>
          <div className="kc-caption">
            {connected
              ? `Connected ${shortDate(status.connected_on)} for ${status.account_name}. No real money moves.`
              : "A sandbox payment provider. Payments go through it, never straight from here."}
          </div>
        </div>
        {connected ? (
          status.provider_reachable === false ? (
            <StatusPill size="sm" status="waiting" label="Unreachable" />
          ) : (
            <StatusPill size="sm" status="executed" label="Connected" />
          )
        ) : (
          <StatusPill size="sm" status="neutral" label="Not connected" />
        )}
      </div>

      {connected ? (
        <dl className="ka-tx-detail">
          <dt>Can</dt>
          <dd>{(status.scopes ?? []).map((s) => (s === "payments.send" ? "Send payments" : "Read payment status")).join(", ")}</dd>
          <dt>Per payment</dt>
          <dd>Up to {money(status.per_payment_cap_minor ?? 0, c)}</dd>
          <dt>Per day</dt>
          <dd>Up to {money(status.daily_cap_minor ?? 0, c)}</dd>
          <dt>Used today</dt>
          <dd>{status.spent_today_minor === null || status.spent_today_minor === undefined ? "—" : money(status.spent_today_minor, c)}</dd>
        </dl>
      ) : null}
      {connected ? (
        <p className="kc-caption">
          The provider enforces these limits itself, so even {APP_NAME} cannot go above them.
        </p>
      ) : null}

      {asking && !connected ? (
        <div className="ka-gmail__consent">
          <div className="kc-label">Before you go to the payment service</div>
          <ul className="ka-gmail__list" aria-label={`What ${APP_NAME} will be able to do`}>
            {status.can_do.map((t) => (
              <li key={t}>
                <Check size={16} strokeWidth={1.5} aria-hidden style={{ color: "var(--success)" }} />
                <span>{t}</span>
              </li>
            ))}
          </ul>
          <ul className="ka-gmail__list" aria-label={`What ${APP_NAME} will not do`}>
            {status.cannot_do.map((t) => (
              <li key={t}>
                <X size={16} strokeWidth={1.5} aria-hidden style={{ color: "var(--text-muted)" }} />
                <span>{t}</span>
              </li>
            ))}
          </ul>
          <p className="kc-caption">
            The provider will show the per-payment and daily limits. You can lower them there before you approve.
          </p>
          <div className="ka-onb__row">
            <Button iconLeft={Banknote} loading={busy} onClick={connect}>
              Continue to {status.provider}
            </Button>
            <Button variant="ghost" onClick={() => setAsking(false)}>
              Cancel
            </Button>
          </div>
        </div>
      ) : (
        <div className="ka-onb__row">
          {status.state === "not_configured" ? (
            <span className="kc-caption">
              To connect, add {(status.missing_settings ?? []).join(", ")} to the server&apos;s .env and start the provider
              (make dev does).
            </span>
          ) : connected ? (
            <Button size="sm" variant="ghost" iconLeft={LogOut} loading={leaving} onClick={disconnect}>
              Disconnect
            </Button>
          ) : (
            <Button size="sm" variant="secondary" iconLeft={Banknote} onClick={() => setAsking(true)}>
              Connect payment service
            </Button>
          )}
        </div>
      )}
      {error ? (
        <p className="kc-caption" style={{ color: "var(--danger)" }} role="alert">
          {error}
        </p>
      ) : null}
    </section>
  );
}

function approvalContext(p: PaymentView) {
  return (
    <>
      Pay <strong>{p.payee_name}</strong> {money(p.amount_minor, p.currency)}
      {p.account_last4 ? ` to the account ending ${p.account_last4} (from your own records)` : ""}. {p.source_label}.
      Your signature covers the payee, the amount and that account: if any of them changes, it will not be paid.
    </>
  );
}

function SuggestionRow({ s, onPay, busy }: { s: SuggestedPayment; onPay: (s: SuggestedPayment) => void; busy: boolean }) {
  return (
    <div className="ka-live__row" style={{ alignItems: "flex-start" }}>
      <div style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column", gap: 4 }}>
        <div className="kc-label">{s.payee_name}</div>
        <div className="kc-caption">
          {s.label}
          {s.due_date ? ` · due ${shortDate(s.due_date)}` : ""}
        </div>
        <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
          {s.covered_by_mandate ? (
            <Badge variant="brand">Runs within your signed limit</Badge>
          ) : (
            <Badge variant="outline" icon={PenLine}>
              Needs your signature
            </Badge>
          )}
          {s.amount_untrusted ? <Badge variant="outline">Amount from an email</Badge> : null}
        </div>
      </div>
      <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 8 }}>
        <span className="kc-label" style={{ fontVariantNumeric: "tabular-nums" }}>
          {money(s.amount_minor, s.currency)}
        </span>
        <Button size="sm" loading={busy} onClick={() => onPay(s)}>
          Pay
        </Button>
      </div>
    </div>
  );
}

function HeldRow({ s, businessId, onPay, busy, reload }: {
  s: SuggestedPayment;
  businessId: string;
  onPay: (s: SuggestedPayment) => void;
  busy: boolean;
  reload: () => void;
}) {
  const { toast } = useAdvisor();
  const [called, setCalled] = useState(false);
  const [saving, setSaving] = useState(false);
  const emailId = s.key.slice("email:".length);

  const markCalled = async () => {
    setSaving(true);
    try {
      await api.verifyCall(businessId, { email_id: emailId });
      toast({ title: "Verification call recorded", description: "It still needs your signature to pay." });
      reload();
    } catch (e) {
      toast({ variant: "danger", title: "Could not record the call", description: errorMessage(e) });
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="kc-alert kc-alert--fraud" role="group" aria-label={`Held payment to ${s.payee_name}`}>
      <span className="kc-alert__icon">
        <ShieldAlert size={20} strokeWidth={1.5} aria-hidden />
      </span>
      <div className="kc-alert__content" style={{ gap: 8 }}>
        <div className="kc-alert__eyebrow">Held: verify before paying</div>
        <div className="kc-alert__title">
          {s.payee_name} · {money(s.amount_minor, s.currency)}
        </div>
        <div className="kc-alert__body">
          {s.label}. {(s.flags ?? []).map((f) => flagLabel(f as Flag["code"])).join(" · ")}
        </div>
        {s.verified ? (
          <div className="ka-onb__row">
            <StatusPill size="sm" status="executed" label="Call done" />
            <Button size="sm" loading={busy} onClick={() => onPay(s)}>
              Prepare payment
            </Button>
          </div>
        ) : (
          <>
            {s.call_script?.length ? (
              <ol className="kc-caption" style={{ margin: 0, paddingLeft: 18, display: "flex", flexDirection: "column", gap: 2 }}>
                {(s.call_script ?? []).map((l) => (
                  <li key={l}>{l}</li>
                ))}
              </ol>
            ) : null}
            <label className="ka-callnum" style={{ cursor: "pointer" }}>
              <Phone size={20} strokeWidth={1.5} style={{ color: "var(--brand-primary)" }} aria-hidden />
              <span style={{ flex: 1 }} className="ka-text">
                I called them on a number from my own records, not from the email, and they confirmed it.
              </span>
              <input type="checkbox" checked={called} onChange={(e) => setCalled(e.target.checked)} />
            </label>
            <div className="ka-onb__row">
              <Button size="sm" variant="secondary" disabled={!called} loading={saving} onClick={markCalled}>
                Mark the call done
              </Button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

function NewPayment({ data, businessId, onCreated }: {
  data: PaymentsOverview;
  businessId: string;
  onCreated: (p: PaymentView) => void;
}) {
  const [payee, setPayee] = useState("");
  const [amount, setAmount] = useState("");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const minor = Math.round(parseFloat(amount) * 100);

  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      onCreated(await api.createPayment(businessId, { payee_id: payee, amount_minor: minor, reason }));
      setAmount("");
      setReason("");
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="ka-stack" style={{ gap: 8 }}>
      <div className="ka-tx-filters">
        <select value={payee} onChange={(e) => setPayee(e.target.value)} aria-label="Payee">
          <option value="">Choose a payee</option>
          {data.payees
            .filter((p) => p.has_account)
            .map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
        </select>
        <input
          type="number"
          min="0.01"
          step="0.01"
          inputMode="decimal"
          placeholder={`Amount (${data.connection.currency})`}
          value={amount}
          onChange={(e) => setAmount(e.target.value)}
          aria-label="Amount"
          style={{ width: 140 }}
        />
        <input
          className="ka-tx-search"
          placeholder="What it is for"
          maxLength={200}
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          aria-label="Reason"
        />
        <Button size="sm" iconLeft={Plus} loading={busy} disabled={!payee || !(minor > 0)} onClick={submit}>
          Request
        </Button>
      </div>
      {error ? (
        <span className="kc-caption" style={{ color: "var(--danger)" }} role="alert">
          {error}
        </span>
      ) : null}
    </div>
  );
}

function AddPayee({ businessId, onAdded }: { businessId: string; onAdded: () => void }) {
  const { toast } = useAdvisor();
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [number, setNumber] = useState("");
  const [again, setAgain] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!open)
    return (
      <div>
        <Button size="sm" variant="ghost" iconLeft={UserPlus} onClick={() => setOpen(true)}>
          Add a payee
        </Button>
      </div>
    );

  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      const p = await api.addPayee(businessId, { name, account_number: number, confirm_account_number: again, confirmed });
      toast({ variant: "success", title: `Payee added: ${p.name}`, description: `Account ending ${p.account_last4}` });
      setOpen(false);
      setName("");
      setNumber("");
      setAgain("");
      setConfirmed(false);
      onAdded();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="ka-gmail" style={{ gap: 10 }}>
      <div className="kc-label">New payee</div>
      <div className="ka-tx-filters">
        <input placeholder="Name" value={name} maxLength={60} onChange={(e) => setName(e.target.value)} aria-label="Payee name" />
        <input
          placeholder="Account number"
          value={number}
          onChange={(e) => setNumber(e.target.value)}
          aria-label="Account number"
          autoComplete="off"
        />
        <input
          placeholder="Account number again"
          value={again}
          onChange={(e) => setAgain(e.target.value)}
          onPaste={(e) => e.preventDefault()}
          aria-label="Account number again"
          autoComplete="off"
        />
      </div>
      <label className="ka-callnum" style={{ cursor: "pointer" }}>
        <Phone size={20} strokeWidth={1.5} style={{ color: "var(--brand-primary)" }} aria-hidden />
        <span style={{ flex: 1 }} className="ka-text">
          I checked this account with the payee myself, not from an email or message.
        </span>
        <input type="checkbox" checked={confirmed} onChange={(e) => setConfirmed(e.target.checked)} />
      </label>
      <div className="ka-onb__row">
        <Button size="sm" loading={busy} disabled={!name || !number || !again || !confirmed} onClick={save}>
          Add payee
        </Button>
        <Button size="sm" variant="ghost" onClick={() => setOpen(false)}>
          Cancel
        </Button>
      </div>
      {error ? (
        <span className="kc-caption" style={{ color: "var(--danger)" }} role="alert">
          {error}
        </span>
      ) : null}
      <span className="kc-caption">
        Only the last four digits are kept for display; the number itself is replaced by a token before it is stored.
        Payments to a new payee always need your signature.
      </span>
    </div>
  );
}

function PaymentDetail({ id, onBack }: { id: string; onBack: () => void }) {
  const { openApproval, pushPanel, toast, paymentVersion } = useAdvisor();
  const { id: businessId, key } = useBusinessKey("payment");
  const res = useApi<PaymentView>(key && `${key}:${id}:${paymentVersion}`, () => api.payment(businessId, id));
  const p = useSticky(res.data);
  const [busy, setBusy] = useState(false);

  const run = async (fn: () => Promise<unknown>, done?: string) => {
    setBusy(true);
    try {
      await fn();
      if (done) toast({ title: done });
      res.reload();
    } catch (e) {
      toast({ variant: "danger", title: "Could not do that", description: errorMessage(e) });
    } finally {
      setBusy(false);
    }
  };

  return (
    <PanelFrame
      title={p ? p.payee_name : "Payment"}
      description={p ? `${p.source_label} · ${shortDate(p.created_on)}` : undefined}
      footer={
        <>
          {p?.status === "awaiting_approval" && p.approval_id ? (
            <Button iconLeft={PenLine} onClick={() => openApproval({ approvalId: p.approval_id!, context: approvalContext(p) })}>
              Review and sign
            </Button>
          ) : null}
          {p && (p.status === "awaiting_approval" || p.status === "proposed") ? (
            <Button variant="secondary" loading={busy} onClick={() => run(() => api.cancelPayment(businessId, p.id), "Payment cancelled")}>
              Cancel payment
            </Button>
          ) : null}
          {p?.status === "sent" ? (
            <Button variant="secondary" iconLeft={RefreshCw} loading={busy} onClick={() => run(() => api.refreshPayment(businessId, p.id))}>
              Check status
            </Button>
          ) : null}
          <Button variant="ghost" size="sm" onClick={onBack}>
            Back to payments
          </Button>
        </>
      }
    >
      {res.error !== undefined && !p ? (
        <p className="ka-text" style={{ color: "var(--danger)" }}>
          Could not load this payment: {errorMessage(res.error)}
        </p>
      ) : !p ? (
        <Skeleton className="h-64 w-full" />
      ) : (
        <div className="ka-stack" style={{ gap: 24 }}>
          <div className="ka-trace-sum">
            <span className="kc-display-number" style={{ fontVariantNumeric: "tabular-nums" }}>
              {money(p.amount_minor, p.currency)}
            </span>
            <span style={{ display: "inline-flex", gap: 10, alignItems: "center" }}>
              <PaymentPill status={p.status} />
              <Steps p={p} />
            </span>
            {p.rule ? <span className="kc-caption">{ruleLabel(p.rule)}</span> : null}
          </div>

          <section className="ka-sec">
            <h3 className="kc-label" style={{ color: "var(--text-muted)" }}>
              What happened
            </h3>
            <ol className="ka-live" style={{ margin: 0, padding: 0, listStyle: "none" }}>
              {(p.events ?? []).map((e) => (
                <li key={e.seq} className="ka-live__row">
                  <PaymentPill status={e.status} />
                  <span className="ka-live__who kc-caption">{noteLabel(e.note)}</span>
                  <span className="kc-caption">{shortDate(e.on_date)}</span>
                </li>
              ))}
            </ol>
          </section>

          <dl className="ka-tx-detail">
            <dt>Reason</dt>
            <dd>{p.reason}</dd>
            <dt>Reference</dt>
            <dd>{p.reference}</dd>
            <dt>Paid to</dt>
            <dd>{p.account_last4 ? `Account ending ${p.account_last4}` : "The account on file"}</dd>
            <dt>Approved by</dt>
            <dd>
              {p.tool === "pay_recurring_bill"
                ? "Your signed standing limit"
                : p.status === "awaiting_approval" || p.status === "proposed"
                  ? "Waiting for your signature"
                  : "Your signature on this exact payment"}
            </dd>
            {p.amount_untrusted ? (
              <>
                <dt>Amount</dt>
                <dd>Came from an email, so it always needs your signature</dd>
              </>
            ) : null}
            {p.provider_payment_id ? (
              <>
                <dt>Provider ID</dt>
                <dd style={{ fontFamily: "var(--font-code)" }}>{p.provider_payment_id}</dd>
              </>
            ) : null}
            {p.idempotency_key ? (
              <>
                <dt>Idempotency key</dt>
                <dd style={{ fontFamily: "var(--font-code)" }}>{p.idempotency_key}</dd>
              </>
            ) : null}
            {p.mandate_id ? (
              <>
                <dt>Mandate</dt>
                <dd style={{ fontFamily: "var(--font-code)" }}>{p.mandate_id}</dd>
              </>
            ) : null}
          </dl>

          {p.status === "settled" ? (
            <section className="ka-mandate" aria-label="Receipt">
              <div className="ka-mandate__top">
                <div className="ka-mandate__title">Receipt</div>
                <StatusPill size="sm" status="executed" label={`Settled ${shortDate(p.settled_on)}`} />
              </div>
              <dl>
                <dt>Paid</dt>
                <dd>
                  {money(p.amount_minor, p.currency)} to {p.payee_name}
                </dd>
                <dt>Fingerprint</dt>
                <dd className="ka-mandate__id">{p.receipt_sha256}</dd>
                <dt>In your ledger</dt>
                <dd>
                  <Button
                    variant="ghost"
                    size="sm"
                    iconRight={ExternalLink}
                    onClick={() => pushPanel({ view: "transactions", txId: p.ledger_tx_id ?? undefined })}
                  >
                    Open the transaction
                  </Button>
                </dd>
              </dl>
              <VerifyOnchain check={() => api.paymentOnchain(businessId, p.id)} />
              <span className="kc-caption">
                Only the receipt&apos;s fingerprint is anchored on a public testnet, never the amount or the payee.
              </span>
            </section>
          ) : null}
        </div>
      )}
    </PanelFrame>
  );
}

export function PaymentsPanel({ openId }: { openId?: string }) {
  const { pushPanel, popPanel, openApproval, toast, paymentVersion } = useAdvisor();
  const { id: businessId, key } = useBusinessKey("payments");
  const [status, setStatus] = useState<"" | Status>("");
  const [payee, setPayee] = useState("");
  const [allSuggestions, setAllSuggestions] = useState(false);
  const [paying, setPaying] = useState<string | null>(null);
  const [changed, setChanged] = useState<Set<string>>(new Set());
  const [nonce, setNonce] = useState(0);
  const res = useApi<PaymentsOverview>(
    key && `${key}:${paymentVersion}:${nonce}:${status}:${payee}`,
    () => api.payments(businessId, { status: status || undefined, payee_id: payee || undefined }),
  );
  const data = useSticky(res.data);
  const reload = useCallback(() => setNonce((n) => n + 1), []);

  // Briefly highlight rows whose status changed since the last load (a live event arrived).
  const seen = useRef<Map<string, Status>>(new Map());
  useEffect(() => {
    if (!res.data) return;
    const moved = res.data.requests.filter((r) => seen.current.has(r.id) && seen.current.get(r.id) !== r.status);
    res.data.requests.forEach((r) => seen.current.set(r.id, r.status));
    if (!moved.length) return;
    setChanged(new Set(moved.map((r) => r.id)));
    const t = window.setTimeout(() => setChanged(new Set()), 2500);
    return () => window.clearTimeout(t);
  }, [res.data]);

  if (openId) return <PaymentDetail id={openId} onBack={popPanel} />;

  const started = (p: PaymentView) => {
    reload();
    if (p.status === "awaiting_approval" && p.approval_id) {
      openApproval({ approvalId: p.approval_id, context: approvalContext(p) });
    } else if (p.status === "sent") {
      toast({ variant: "success", title: `Sent: ${p.payee_name}`, description: "Within your signed limit. Settling now." });
    } else if (p.status === "failed" || p.status === "denied") {
      toast({ variant: "danger", title: `Not paid: ${p.payee_name}`, description: p.rule ? ruleLabel(p.rule) : undefined });
    }
  };

  const pay = async (s: SuggestedPayment) => {
    setPaying(s.key);
    try {
      started(await api.createPayment(businessId, { source: s.key }));
    } catch (e) {
      toast({ variant: "danger", title: "Could not prepare the payment", description: errorMessage(e) });
    } finally {
      setPaying(null);
    }
  };

  const due = data?.suggestions.filter((s) => s.source_kind !== "email") ?? [];
  const held = data?.suggestions.filter((s) => s.source_kind === "email") ?? [];
  const waiting = data?.requests.filter((r) => r.status === "awaiting_approval").length ?? 0;

  return (
    <PanelFrame
      title="Payments"
      description={waiting ? `${waiting} waiting for your signature` : "Pay suppliers and bills through your connected service"}
    >
      {res.error !== undefined && !data ? (
        <p className="ka-text" style={{ color: "var(--danger)" }}>
          Could not load payments: {errorMessage(res.error)}
        </p>
      ) : !data ? (
        <Skeleton className="h-96 w-full" />
      ) : (
        <div className="ka-stack" style={{ gap: 28 }}>
          <ConnectionCard status={data.connection} businessId={businessId} reload={reload} />

          <section className="ka-sec">
            <div className="ka-sechead">
              <h3 className="kc-section-title">Due soon</h3>
              <span className="kc-caption">From your bills and invoices</span>
            </div>
            {due.length === 0 ? (
              <p className="kc-caption">Nothing due in the next two weeks.</p>
            ) : (
              <div className="ka-live">
                {(allSuggestions ? due : due.slice(0, FIRST)).map((s) => (
                  <SuggestionRow key={s.key} s={s} onPay={pay} busy={paying === s.key} />
                ))}
              </div>
            )}
            {due.length > FIRST ? (
              <div>
                <Button variant="ghost" size="sm" onClick={() => setAllSuggestions((x) => !x)}>
                  {allSuggestions ? "Show fewer" : `Show all ${due.length}`}
                </Button>
              </div>
            ) : null}
          </section>

          {held.length ? (
            <section className="ka-sec">
              <h3 className="kc-section-title">Held by the inbox check</h3>
              {held.map((s) => (
                <HeldRow key={s.key} s={s} businessId={businessId} onPay={pay} busy={paying === s.key} reload={reload} />
              ))}
            </section>
          ) : null}

          <section className="ka-sec">
            <h3 className="kc-section-title">New payment</h3>
            <NewPayment data={data} businessId={businessId} onCreated={started} />
          </section>

          <section className="ka-sec">
            <div className="ka-sechead">
              <h3 className="kc-section-title">History</h3>
            </div>
            <div className="ka-tx-filters">
              <select value={status} onChange={(e) => setStatus(e.target.value as "" | Status)} aria-label="Status">
                <option value="">Any status</option>
                {(Object.keys(STATUS) as Status[]).map((s) => (
                  <option key={s} value={s}>
                    {STATUS[s].label}
                  </option>
                ))}
              </select>
              <select value={payee} onChange={(e) => setPayee(e.target.value)} aria-label="Payee">
                <option value="">Any payee</option>
                {data.payees.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name}
                  </option>
                ))}
              </select>
            </div>
            <Table<PaymentView>
              density="compact"
              rowKey={(r) => r.id}
              rows={data.requests}
              onRowClick={(r) => pushPanel({ view: "payments", paymentId: r.id })}
              rowClassName={(r) => (changed.has(r.id) ? "kc-table__row--new" : undefined)}
              empty="No payments yet."
              columns={[
                { key: "date", header: "Date", width: 70, render: (r) => shortDate(r.created_on) },
                {
                  key: "who",
                  header: "Payee",
                  render: (r) => (
                    <div>
                      <div style={{ fontWeight: 500 }}>{r.payee_name}</div>
                      <div className="kc-caption">{r.source_label}</div>
                    </div>
                  ),
                },
                {
                  key: "status",
                  header: "Status",
                  render: (r) => (
                    <span style={{ display: "inline-flex", flexDirection: "column", gap: 4 }}>
                      <PaymentPill status={r.status} />
                      <Steps p={r} />
                    </span>
                  ),
                },
                {
                  key: "amount",
                  header: "Amount",
                  align: "right",
                  render: (r) => money(r.amount_minor, r.currency),
                },
              ]}
            />
          </section>

          <section className="ka-sec">
            <h3 className="kc-section-title">Payees</h3>
            <Table
              density="compact"
              rowKey={(p) => p.id}
              rows={data.payees}
              columns={[
                {
                  key: "name",
                  header: "Name",
                  render: (p) => (
                    <div>
                      <div style={{ fontWeight: 500 }}>{p.name}</div>
                      {p.account_changed ? <div className="kc-caption">Bank details changed with your signature</div> : null}
                    </div>
                  ),
                },
                {
                  key: "acct",
                  header: "Account",
                  render: (p) => (p.account_last4 ? `ending ${p.account_last4}` : "none on file"),
                },
                {
                  key: "badge",
                  header: "",
                  align: "right",
                  render: (p) =>
                    p.verified ? (
                      <StatusPill size="sm" status="executed" label="Verified" />
                    ) : (
                      <StatusPill size="sm" status="neutral" label="Added by you" />
                    ),
                },
              ]}
            />
            <AddPayee businessId={businessId} onAdded={reload} />
            <span className="kc-caption">
              Verified payees come from your own contact book. {APP_NAME} never pays an account taken from an email.
            </span>
          </section>
        </div>
      )}
    </PanelFrame>
  );
}
