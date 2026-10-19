"use client";

import { Ban, Copy, EyeOff, Phone, RotateCw, ShieldAlert, ShieldCheck } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { useBusinessKey } from "@/components/business-context";
import { AlertBanner } from "@/components/kc/alert-banner";
import { Badge } from "@/components/kc/badge";
import { Button } from "@/components/kc/button";
import { FactNumber } from "@/components/kc/fact";
import { Table } from "@/components/kc/misc";
import { StatusPill } from "@/components/kc/status-pill";
import { Skeleton } from "@/components/ui/skeleton";
import { api, inboxStream, type InboxStreamEvent } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import { flagLabel, sentence, shortDate } from "@/lib/format";
import type { Flag, InboxDetail, InboxItem, InboxList } from "@/lib/types";
import { useApi } from "@/lib/use-api";

import { PanelFrame } from "./detail-panel";
import { GmailConnectionCard, useGmailConnection } from "./gmail-connection";
import { useAdvisor } from "./state";

const moneyFact = (item: InboxItem) => item.facts.find((f) => f.unit === "money");
const sender = (item: InboxItem) => item.record.from_display_name || item.record.from_address;

const SOURCE: Record<string, string> = { gmail: "Gmail", mailbox: "Sandbox", upload: "Upload" };

type Live = InboxStreamEvent & { done: boolean };
const STAGES = ["received", "extracting", "checking"];
const STAGE_LABEL: Record<string, string> = {
  received: "Received",
  extracting: "Reading in quarantine…",
  checking: "Running fraud checks…",
  held: "Held",
  failed: "Could not read",
};

function livePill(r: Live) {
  if (r.stage === "held" || r.stage === "failed")
    return <StatusPill size="sm" status="blocked" label={STAGE_LABEL[r.stage]} />;
  if (r.stage === "flagged") return <StatusPill size="sm" status="waiting" label="Check first" />;
  return <StatusPill size="sm" status="executed" label="Checked" />;
}

/** Messages moving through the pipeline right now: received, reading in quarantine, checks, verdict. */
function LiveRows({ rows }: { rows: Live[] }) {
  if (!rows.length) return null;
  return (
    <div className="ka-live" aria-live="polite">
      {rows.map((r) => {
        const at = STAGES.indexOf(r.stage ?? "received");
        const bad = r.stage === "held" || r.stage === "failed";
        return (
          <div key={r.email_id ?? r.seq} className="ka-live__row">
            <Badge variant="outline">{SOURCE[r.source ?? ""] ?? "Email"}</Badge>
            <div className="ka-live__who">
              <div style={{ fontWeight: 500 }}>{r.sender ?? "New email"}</div>
              <div className="kc-caption">{r.subject}</div>
            </div>
            <div className="ka-live__steps" aria-hidden>
              {[0, 1, 2, 3].map((i) => (
                <span
                  key={i}
                  className={
                    "ka-live__step" +
                    (r.done ? (bad && i === 3 ? " is-bad" : " is-done") : i <= at ? " is-done" : "")
                  }
                />
              ))}
            </div>
            {r.done ? livePill(r) : <span className="kc-caption">{STAGE_LABEL[r.stage ?? "received"]}</span>}
          </div>
        );
      })}
    </div>
  );
}

function riskPill(item: InboxItem) {
  const s = item.record.sentinel;
  if (s.hold) return <StatusPill size="sm" status="blocked" label="Held" />;
  if (s.risk === "review") return <StatusPill size="sm" status="waiting" label="Check first" />;
  return <StatusPill size="sm" status="executed" label="Checked" />;
}

export function InboxPanel() {
  const { pushPanel, toast } = useAdvisor();
  const { id, key } = useBusinessKey("inbox-panel");
  const inbox = useApi(key, () => api.inbox(id));
  const [last, setLast] = useState<InboxList | undefined>(undefined);
  if (inbox.data && inbox.data !== last) setLast(inbox.data);
  const data = inbox.data ?? last; // keep the table on screen while a live update reloads it
  const gmail = useGmailConnection(id);
  const { setStatus } = gmail;
  const [syncing, setSyncing] = useState(false);
  const [live, setLive] = useState<Live[]>([]);
  const reload = useRef(inbox.reload);
  useEffect(() => {
    reload.current = inbox.reload;
  }, [inbox.reload]);

  useEffect(() => {
    if (!key) return;
    const ctl = new AbortController();
    (async () => {
      try {
        for await (const { data: e } of inboxStream(id, ctl.signal)) {
          if (e.kind === "connection" && e.connection) {
            setStatus(e.connection);
            continue;
          }
          if (!e.email_id) continue;
          const done = !STAGES.includes(e.stage ?? "received");
          setLive((rows) => [{ ...e, done }, ...rows.filter((r) => r.email_id !== e.email_id)].slice(0, 6));
          if (!done) continue;
          reload.current();
          if (e.stage === "held")
            toast({
              variant: "danger",
              title: `Held: ${e.sender ?? "an email"}`,
              description: e.flags.length ? e.flags.map((f) => flagLabel(f as Flag["code"])).join(" · ") : undefined,
            });
          window.setTimeout(() => setLive((rows) => rows.filter((r) => r.email_id !== e.email_id)), 4000);
        }
      } catch {
        // Stream closed (navigation, server restart): the list still loads on demand.
      }
    })();
    return () => ctl.abort();
  }, [id, key, setStatus, toast]);

  const sync = async () => {
    setSyncing(true);
    try {
      const fromGmail =
        gmail.status?.source === "gmail" && gmail.status.state !== "reconnect_needed"
          ? (await api.gmailPoll(id)).processed.length
          : 0;
      const r = await api.syncInbox(id);
      const n = r.processed.length + fromGmail;
      toast({
        variant: r.held.length ? "danger" : "default",
        title: n === 0 ? "No new email" : n === 1 ? "One new email checked" : `${n} new emails checked`,
        description: r.held.length
          ? `${r.held.length === 1 ? "One message" : `${r.held.length} messages`} held for you to check.`
          : r.failed.length
            ? `${r.failed.length} could not be read.`
            : undefined,
      });
      inbox.reload();
    } catch (e) {
      toast({ variant: "danger", title: "Could not check email", description: errorMessage(e) });
    } finally {
      setSyncing(false);
    }
  };

  return (
    <PanelFrame
      title="Inbox"
      description={data ? `${data.total} finance emails · ${data.held} held` : "Finance emails"}
      footer={
        <Button variant="secondary" size="sm" iconLeft={RotateCw} loading={syncing} onClick={sync}>
          Check for new email
        </Button>
      }
    >
      {inbox.error !== undefined ? (
        <p className="ka-text" style={{ color: "var(--danger)" }}>
          Could not load the inbox: {errorMessage(inbox.error)}
        </p>
      ) : !data ? (
        <Skeleton className="h-64 w-full" />
      ) : (
        <div className="ka-stack">
          <GmailConnectionCard gmail={gmail} />
          <LiveRows rows={live} />
          <Table<InboxItem>
            rowKey={(r) => r.record.email_id}
            rows={data.items}
            empty="No finance email yet. Check for new email to fetch it."
            onRowClick={(r) => pushPanel({ view: "email", emailId: r.record.email_id })}
            columns={[
              {
                key: "from",
                header: "From",
                render: (r) => (
                  <div>
                    <div style={{ fontWeight: 500, display: "flex", alignItems: "center", gap: 8 }}>
                      {sender(r)}
                      <Badge variant="outline">{SOURCE[r.record.source] ?? r.record.source}</Badge>
                    </div>
                    <div className="kc-caption" style={{ color: r.record.sentinel.hold ? "var(--danger)" : undefined }}>
                      {r.record.sentinel.flags?.length
                        ? r.record.sentinel.flags.map((f) => flagLabel(f.code)).join(" · ")
                        : r.record.subject}
                    </div>
                  </div>
                ),
              },
              { key: "status", header: "Status", render: riskPill },
              {
                key: "amount",
                header: "Amount",
                align: "right",
                render: (r) => {
                  const f = moneyFact(r);
                  return f ? <FactNumber fact={f} /> : <span className="kc-caption">none</span>;
                },
              },
            ]}
          />
          <div className="kc-caption">
            Every message is read by a quarantined reader with no tools. The assistant only ever sees checked fields,
            never the text.
          </div>
        </div>
      )}
    </PanelFrame>
  );
}

function evidence(flag: Flag): string {
  const parts = Object.entries(flag.evidence ?? {})
    .filter(([, v]) => typeof v === "string" && v)
    .map(([k, v]) => `${sentence(k)}: ${v}`);
  return parts.length ? `${parts.join(". ")}.` : "";
}

export function EmailPanel({ emailId }: { emailId: string }) {
  const { toast } = useAdvisor();
  const { id, key } = useBusinessKey("email");
  const detail = useApi<InboxDetail>(key && `${key}:${emailId}`, () => api.inboxItem(id, emailId));
  const [kept, setKept] = useState(false);

  const d = detail.data;
  const r = d?.item.record;
  const flags = r?.sentinel.flags ?? [];
  const script = r?.sentinel.call_script;
  const instruction = flags.some((f) => f.code === "instruction_like_text" || f.code === "hidden_text");
  const amount = d ? moneyFact(d.item) : undefined;

  const title = !r
    ? "Email"
    : r.sentinel.hold
      ? "This email is suspicious"
      : r.sentinel.risk === "review"
        ? "Check this email"
        : "Email";
  const copyScript = async () => {
    if (!script) return;
    try {
      await navigator.clipboard.writeText([script.call, ...script.lines].join("\n"));
      toast({ title: "Call script copied" });
    } catch {
      toast({ variant: "danger", title: "Could not copy", description: "Your browser blocked the clipboard." });
    }
  };

  const footer = !r ? null : r.sentinel.hold && !kept ? (
    <>
      <Button
        variant="destructive"
        size="sm"
        iconLeft={Ban}
        onClick={() => {
          setKept(true);
          toast({ variant: "danger", title: "Payment stays blocked", description: sender(d!.item) });
        }}
      >
        Keep payment blocked
      </Button>
      {script ? (
        <Button variant="ghost" size="sm" iconLeft={Copy} onClick={copyScript}>
          Copy call script
        </Button>
      ) : null}
    </>
  ) : r.sentinel.hold ? (
    <span className="kc-caption" style={{ display: "flex", alignItems: "center", gap: 8 }}>
      <Ban size={16} strokeWidth={1.5} style={{ color: "var(--danger)" }} aria-hidden />
      Payment stays blocked until you check with them.
    </span>
  ) : null;

  return (
    <PanelFrame title={title} description={r ? `${sender(d!.item)} · ${r.subject}` : undefined} footer={footer}>
      {detail.error !== undefined ? (
        <p className="ka-text" style={{ color: "var(--danger)" }}>
          Could not load this email: {errorMessage(detail.error)}
        </p>
      ) : !d || !r ? (
        <Skeleton className="h-96 w-full" />
      ) : (
        <div className="ka-stack">
          {instruction ? (
            <AlertBanner variant="info" eyebrow="Ignored" title="Instructions to the assistant were found and ignored">
              The text was treated as data. The assistant never saw it, only the checked fields below.
            </AlertBanner>
          ) : null}
          <div className="ka-email">
            <section className="ka-sec">
              <div className="kc-label" style={{ color: "var(--text-muted)", fontWeight: 400 }}>
                Original email
              </div>
              <article className="ka-mail">
                <dl className="ka-mail__hdr">
                  <dt>From</dt>
                  <dd>
                    {r.from_display_name ? `${r.from_display_name} ` : ""}&lt;
                    <span
                      className={
                        flags.some((f) => f.code === "lookalike_domain") && !r.reply_to_address ? "ka-flag" : undefined
                      }
                    >
                      {r.from_address}
                    </span>
                    &gt;
                  </dd>
                  {r.reply_to_address ? (
                    <>
                      <dt>Reply to</dt>
                      <dd>
                        <span
                          className={
                            flags.some((f) => f.code === "reply_to_mismatch" || f.code === "lookalike_domain")
                              ? "ka-flag"
                              : undefined
                          }
                        >
                          {r.reply_to_address}
                        </span>
                      </dd>
                    </>
                  ) : null}
                  <dt>Date</dt>
                  <dd>{shortDate(r.received_on ?? r.processed_on)}</dd>
                  <dt>Subject</dt>
                  <dd>{r.subject}</dd>
                </dl>
                {d.body_text
                  .split(/\n\s*\n/)
                  .filter((p) => p.trim())
                  .map((p, i) => (
                    <p key={i} style={{ whiteSpace: "pre-line" }}>
                      {p.trim()}
                    </p>
                  ))}
                {r.attachments.length ? (
                  <div className="kc-caption">Attached: {r.attachments.map((a) => a.filename).join(", ")}</div>
                ) : null}
              </article>
              {d.hidden_text.length ? (
                <div className="ka-sec" style={{ gap: 8 }}>
                  <div
                    className="kc-label"
                    style={{ color: "var(--danger)", display: "flex", alignItems: "center", gap: 6 }}
                  >
                    <EyeOff size={16} strokeWidth={1.5} aria-hidden />
                    Hidden text in this message
                  </div>
                  {d.hidden_text.map((t, i) => (
                    <p key={i} className="ka-mail" style={{ margin: 0 }}>
                      <span className="ka-flag">{t}</span>
                    </p>
                  ))}
                </div>
              ) : null}
            </section>
            <section className="ka-sec" style={{ gap: 16 }}>
              {flags.length ? (
                <>
                  <div
                    className="kc-label"
                    style={{ color: "var(--danger)", fontWeight: 500, display: "flex", alignItems: "center", gap: 6 }}
                  >
                    <ShieldAlert size={16} strokeWidth={1.5} aria-hidden />
                    {flags.length === 1 ? "One red flag" : `${flags.length} red flags`}
                  </div>
                  <ol className="ka-flags">
                    {flags.map((f, i) => (
                      <li key={`${f.code}-${i}`}>
                        <span className="n">{i + 1}</span>
                        <span className="t">{flagLabel(f.code)}</span>
                        <span className="d">
                          {evidence(f) || (f.severity === "high" ? "High risk." : "Worth a check.")}
                          {f.detected_by.includes("code") ? " Found by a code check." : " Noticed by the reader."}
                        </span>
                      </li>
                    ))}
                  </ol>
                </>
              ) : (
                <div
                  className="kc-label"
                  style={{ color: "var(--success)", display: "flex", alignItems: "center", gap: 6 }}
                >
                  <ShieldCheck size={16} strokeWidth={1.5} aria-hidden />
                  No red flags
                </div>
              )}
              <div className="ka-sec" style={{ gap: 6 }}>
                <div className="kc-label" style={{ color: "var(--text-muted)", fontWeight: 400 }}>
                  What I took from it
                </div>
                <dl
                  className="ka-mail__hdr"
                  style={{ borderBottom: 0, paddingBottom: 0, gridTemplateColumns: "96px minmax(0,1fr)" }}
                >
                  <dt>Kind</dt>
                  <dd>{sentence(r.fields.category ?? "other")}</dd>
                  {amount ? (
                    <>
                      <dt>Amount</dt>
                      <dd>
                        <FactNumber fact={amount} />
                      </dd>
                    </>
                  ) : null}
                  {r.fields.invoice_number ? (
                    <>
                      <dt>Invoice</dt>
                      <dd>{r.fields.invoice_number.value}</dd>
                    </>
                  ) : null}
                  {r.fields.due_date ? (
                    <>
                      <dt>Due</dt>
                      <dd>{shortDate(r.fields.due_date.value)}</dd>
                    </>
                  ) : null}
                  {r.fields.payee_account_last4 ? (
                    <>
                      <dt>Pay to</dt>
                      <dd>Account ··{r.fields.payee_account_last4}</dd>
                    </>
                  ) : null}
                  <dt>Forecast</dt>
                  <dd>{sentence(r.feed)}</dd>
                </dl>
              </div>
            </section>
          </div>
          {script ? (
            <section className="ka-sec" style={{ gap: 16 }}>
              <h3 className="kc-section-title">Check with a phone call</h3>
              <div className="ka-callnum">
                <Phone size={20} strokeWidth={1.5} style={{ color: "var(--brand-primary)" }} aria-hidden />
                <div style={{ flex: 1 }}>
                  <div className="num">{script.call}</div>
                  <div className="kc-caption">{script.number_source}</div>
                </div>
              </div>
              <ol className="ka-script">
                {script.lines.map((l, i) => (
                  <li key={i}>
                    <span>{l}</span>
                  </li>
                ))}
              </ol>
            </section>
          ) : null}
        </div>
      )}
    </PanelFrame>
  );
}
