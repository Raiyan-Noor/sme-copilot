"use client";

import {
  ArrowLeft,
  ArrowUpRight,
  Banknote,
  Calculator,
  CircleAlert,
  CircleCheck,
  FastForward,
  Mail,
  Moon,
  Newspaper,
  PenLine,
  ShieldAlert,
  Sparkles,
  TrendingUp,
} from "lucide-react";
import { useEffect, useState } from "react";

import { useBusiness, useBusinessKey } from "@/components/business-context";
import { Button } from "@/components/kc/button";
import { FactNumber, FactText } from "@/components/kc/fact";
import { ApiError, api } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import { flagLabel, ruleLabel, shortDate, toolTitle } from "@/lib/format";
import type { ActivityRow, BriefActivity, Flag, Stamp } from "@/lib/types";
import { useApi } from "@/lib/use-api";
import { cn } from "@/lib/utils";

import { startPayment } from "./approve";
import { useFastForward } from "./fast-forward";
import { Sparkline } from "./rail";
import { useAdvisor } from "./state";

const REFRESH_MS = 15000;

function useSticky<T>(value: T | undefined): T | undefined {
  const [last, setLast] = useState<T | undefined>(value);
  if (value !== undefined && value !== last) setLast(value);
  return value ?? last;
}

/** A feed row with its defaulted fields filled in. */
type FeedRow = ActivityRow & Required<Pick<ActivityRow, "flags" | "approval_ids" | "detail" | "facts">>;
const norm = (r: ActivityRow): FeedRow => ({
  ...r,
  flags: r.flags ?? [],
  approval_ids: r.approval_ids ?? [],
  detail: r.detail ?? "",
  facts: r.facts ?? {},
});

const hhmm = (s: Stamp | null | undefined) => (s?.time ? s.time.slice(0, 5) : "");

function weekday(iso: string): string {
  const d = new Date(`${iso}T00:00:00`);
  return Number.isNaN(d.getTime()) ? "" : d.toLocaleDateString("en-GB", { weekday: "short" });
}

/** The time an audit entry was logged; its date as well when it is not the brief's day, or only its date when the
 * entry predates the log keeping times. Never a made-up time. */
function When({ at, day }: { at: Stamp; day: string }) {
  const t = hhmm(at);
  return (
    <span className="ka-bt__time" title={`Audit record ${at.seq}`}>
      {t || shortDate(at.date)}
      {t && at.date !== day ? <span className="d">{shortDate(at.date)}</span> : null}
    </span>
  );
}

function RowIcon({ row }: { row: FeedRow }) {
  const p = { size: 18, strokeWidth: 1.5 };
  if (row.kind === "payment") return <Banknote {...p} />;
  if (row.kind === "held") return <ShieldAlert {...p} />;
  if (row.kind === "insight") return <TrendingUp {...p} />;
  if (row.kind === "approval") return row.tool === "send_email" ? <Mail {...p} /> : <PenLine {...p} />;
  if (row.title.startsWith("Overnight")) return <Moon {...p} />;
  if (row.title === "Morning brief ready") return <Newspaper {...p} />;
  if (row.title === "Cash buffer recalculated") return <Calculator {...p} />;
  if (row.title === "Brief written") return <Sparkles {...p} />;
  return row.state === "denied" ? <CircleAlert {...p} /> : <CircleCheck {...p} />;
}

function rowTitle(row: FeedRow): string {
  if (row.kind === "held") return row.flags.length ? `${flagLabel(row.flags[0] as Flag["code"])} held` : "Message held";
  return row.title || (row.tool ? toolTitle(row.tool) : "Done");
}

function rowDetail(row: FeedRow): React.ReactNode {
  if (row.kind === "held") {
    const rest = row.flags.slice(1).map((f) => flagLabel(f as Flag["code"]).toLowerCase());
    return [row.sender, ...rest, "payment blocked"].filter(Boolean).join(" · ");
  }
  if (row.state === "denied" && row.rule && !row.detail) return ruleLabel(row.rule);
  return <FactText text={row.detail} facts={row.facts} />;
}

/**
 * One feed row. A row that would send a message or move money waits for the owner; Approve goes through the same
 * paths as everywhere else: the approval sheet the Outbox opens (the owner signs in the browser and the gateway
 * verifies), the Outbox itself for a group of emails (there is no batch signing), or the Payments flow, which asks
 * the gateway and opens that same sheet. Held emails can only be reviewed. A refusal shows in the row.
 */
function Row({ row, day, owner, onChanged }: { row: FeedRow; day: string; owner: string; onChanged: () => void }) {
  const { openApproval, openPanel, pushPanel, addPending, toast } = useAdvisor();
  const { id } = useBusinessKey("brief-tab");
  const [busy, setBusy] = useState(false);
  const [refusal, setRefusal] = useState<string | null>(null);
  const waiting = row.state === "waiting";
  const shownRefusal = refusal ?? (row.rule && row.state !== "done" ? ruleLabel(row.rule) : null);

  const approve = async () => {
    setRefusal(null);
    if (row.kind === "payment" && row.payment_key) {
      setBusy(true);
      try {
        const p = await startPayment(id, row.payment_key, { openApproval, addPending, toast });
        if (p.status === "denied" || p.status === "failed") setRefusal(ruleLabel(p.rule ?? "denied"));
      } catch (e) {
        setRefusal(errorMessage(e));
      } finally {
        setBusy(false);
        onChanged();
      }
      return;
    }
    if (row.approval_ids.length > 1) {
      openPanel("outbox"); // each email is read and signed on its own
      return;
    }
    const approvalId = row.approval_ids[0];
    if (approvalId) openApproval({ approvalId, context: <FactText text={row.detail} facts={row.facts} /> });
  };

  return (
    <li className={cn("ka-bt__row", waiting && "is-waiting", row.kind === "held" && "is-blocked")}>
      <When at={row.at} day={day} />
      <span className={cn("ka-bt__icon", `is-${row.kind}`, row.state === "denied" && "is-denied")} aria-hidden>
        <RowIcon row={row} />
      </span>
      <span className="ka-bt__text">
        <span className="t">{rowTitle(row)}</span>
        <span className="d">{rowDetail(row)}</span>
        {shownRefusal ? (
          <span className="r" role="alert">
            Not done: {shownRefusal}
          </span>
        ) : null}
      </span>
      <span className="ka-bt__status">
        {waiting ? (
          <>
            <span className="ka-bt__pill is-waiting">Waiting for {owner}</span>
            <button
              type="button"
              className="ka-bt__approve"
              onClick={approve}
              disabled={busy}
              aria-label={`Approve: ${rowTitle(row)}`}
            >
              {busy ? "Preparing…" : "Approve"}
            </button>
          </>
        ) : row.kind === "held" ? (
          <>
            <span className="ka-bt__pill is-blocked">Blocked</span>
            {row.email_id ? (
              <Button
                variant="secondary"
                size="sm"
                onClick={() => pushPanel({ view: "email", emailId: row.email_id! })}
              >
                Review
              </Button>
            ) : null}
          </>
        ) : row.state === "denied" ? (
          <span className="ka-bt__pill is-blocked">Not done</span>
        ) : row.kind === "insight" ? (
          <span className="ka-bt__insight">Insight</span>
        ) : (
          <span className="ka-bt__done">
            {row.done_label ?? "Done"}
            {row.completed && hhmm(row.completed) ? ` · ${hhmm(row.completed)}` : ""}
          </span>
        )}
      </span>
    </li>
  );
}

/** The left column: who, the headline, cash and buffer, the next 30 days, and the audit log check. */
function Summary({ feed, waitingCount }: { feed: BriefActivity; waitingCount: number }) {
  const { openPanel, ledgerVersion } = useAdvisor();
  const { session } = useBusiness();
  const { id, key } = useBusinessKey("brief-tab");
  const cash = useApi(key && `${key}:cash:${ledgerVersion}`, () => api.cash(id));
  const forecast = useApi(key && `${key}:forecast:${ledgerVersion}`, () => api.forecast(id));
  const verify = useApi(`verify:${session}`, api.auditVerify);
  const c = cash.data;
  const h30 = forecast.data?.horizons.find((h) => h.days === 30);

  return (
    <div className="ka-bt__left">
      <span className="kc-caption">
        {feed.business_name} · Skill Pack: {feed.pack_name}
      </span>
      <p className="ka-bt__headline">
        {c ? (
          <>
            Cash is <FactNumber fact={c.balance} />, with <FactNumber fact={c.runway_days} /> of runway.{" "}
          </>
        ) : null}
        {waitingCount === 0
          ? "Nothing needs your signature today."
          : waitingCount === 1
            ? "One item needs your signature today."
            : `${waitingCount} items need your signature today.`}
      </p>
      <div className="ka-bt__tiles">
        <div className="ka-bt__tile">
          <span className="kc-caption">Cash on hand</span>
          <span className="v">{c ? <FactNumber fact={c.balance} /> : null}</span>
        </div>
        <div className="ka-bt__tile">
          <span className="kc-caption">Cash buffer</span>
          <span className="v">{c ? <FactNumber fact={c.buffer_days} /> : null}</span>
        </div>
      </div>
      <div className="ka-bt__tile ka-bt__spark">
        <span className="ka-spark__row">
          <button type="button" className="ka-bt__sparklink kc-caption" onClick={() => openPanel("cash")}>
            Cash, next 30 days
            <ArrowUpRight size={14} strokeWidth={1.5} aria-hidden />
          </button>
          <span className="kc-caption">
            {h30 ? (
              <>
                Low <FactNumber fact={h30.min_balance} /> · <FactNumber fact={h30.min_balance_date} />
              </>
            ) : null}
          </span>
        </span>
        {forecast.data ? <Sparkline forecast={forecast.data} w={360} /> : <span style={{ height: 64 }} />}
        <span className="ka-spark__row">
          <span className="kc-caption">{h30 ? <>Ends near <FactNumber fact={h30.end_balance} /></> : ""}</span>
          <span className="kc-caption">{h30 ? <FactNumber fact={h30.end_date} /> : ""}</span>
        </span>
      </div>
      <button type="button" className="ka-anchor ka-bt__audit" onClick={() => openPanel("trust", { tab: "audit" })}>
        {verify.data && !verify.data.ok ? (
          <span style={{ color: "var(--danger)", display: "flex" }}>
            <CircleAlert size={14} strokeWidth={1.5} aria-hidden />
          </span>
        ) : (
          <span className="ok">
            <CircleCheck size={14} strokeWidth={1.5} aria-hidden />
          </span>
        )}
        <span>
          {!verify.data
            ? "Checking the audit log…"
            : verify.data.ok
              ? `Audit log verified · ${verify.data.entries} records`
              : "Audit log broken"}
        </span>
      </button>
    </div>
  );
}

/**
 * The Morning brief as its own tab (/brief): the same brief's numbers on the left, and on the right what the
 * overnight run did, read back from the audit log (GET /brief/activity). Every time shown is an audit entry's time.
 * The chat message stays as it is; this is an addition opened from its Expand button.
 */
export function BriefTab() {
  const { closeBriefTab, resolved, paymentVersion, ledgerVersion, addPending } = useAdvisor();
  const { id, key } = useBusinessKey("brief-tab");
  const [nonce, setNonce] = useState(0);
  const settled = Object.keys(resolved).length;
  const res = useApi<BriefActivity>(
    key && `${key}:activity:${settled}:${paymentVersion}:${ledgerVersion}:${nonce}`,
    () => api.briefActivity(id),
  );
  const feed = useSticky(res.data);
  const rows = feed ? feed.rows.map(norm) : [];
  const ff = useFastForward();

  useEffect(() => {
    const t = window.setInterval(() => setNonce((n) => n + 1), REFRESH_MS);
    return () => window.clearInterval(t);
  }, []);

  useEffect(() => {
    if (feed) addPending(feed.rows.flatMap((r) => r.approval_ids ?? []));
  }, [feed, addPending]);

  const missing = res.error instanceof ApiError && res.error.status === 404;
  const day = feed ? String(feed.as_of.value) : "";
  const waitingCount = rows
    .filter((r) => r.state === "waiting")
    .reduce((n, r) => n + Math.max(1, r.approval_ids.length), 0);
  const owner = feed?.owner_first_name || "you";

  return (
    <div className="ka-scroll">
      <div className="ka-bt">
        <header className="ka-bt__head">
          <h1 className="ka-bt__title">
            Morning brief
            {feed ? (
              <span className="m">
                {" "}
                · {weekday(day)} <FactNumber fact={feed.as_of} />
                {hhmm(feed.brief_at) ? `, ${hhmm(feed.brief_at)}` : ""}
              </span>
            ) : null}
          </h1>
          <Button variant="ghost" size="sm" iconLeft={ArrowLeft} onClick={closeBriefTab}>
            Back to chat
          </Button>
        </header>

        {missing ? (
          <div className="ka-bt__card ka-bt__empty">
            <p className="ka-text">No brief yet for today. Fast-forward to tomorrow morning and the overnight checks will run.</p>
            <div>
              <Button variant="secondary" size="sm" iconLeft={FastForward} loading={ff.busy} onClick={ff.run}>
                Fast-forward to tomorrow 7:00
              </Button>
            </div>
          </div>
        ) : res.error !== undefined && !feed ? (
          <p className="ka-text" style={{ color: "var(--danger)" }}>
            Could not load the brief: {errorMessage(res.error)}
          </p>
        ) : !feed ? (
          <div className="ka-bt__card" style={{ minHeight: 420 }} aria-busy="true" />
        ) : (
          <div className="ka-bt__card">
            <Summary feed={feed} waitingCount={waitingCount} />
            <section className="ka-bt__feed" aria-label="Live activity">
              <div className="ka-bt__feedhead">
                <span className="ka-bt__live" aria-hidden />
                <span className="ka-bt__feedtitle">Live activity</span>
                <span className="kc-caption">overnight run</span>
                <span className="kc-caption ka-bt__limits">Acts only within the limits {owner} signed</span>
              </div>
              {rows.length === 0 ? (
                <p className="kc-caption">Nothing logged for this run.</p>
              ) : (
                <ol className="ka-bt__rows">
                  {rows.map((r) => (
                    <Row key={r.id} row={r} day={day} owner={owner} onChanged={() => setNonce((n) => n + 1)} />
                  ))}
                </ol>
              )}
            </section>
          </div>
        )}
      </div>
    </div>
  );
}
