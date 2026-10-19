"use client";

import { FlaskConical, Paperclip, Send, ShieldAlert, ShieldCheck } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { useBusiness } from "@/components/business-context";
import { AlertBanner } from "@/components/kc/alert-banner";
import { Badge } from "@/components/kc/badge";
import { Button } from "@/components/kc/button";
import { StatusPill } from "@/components/kc/status-pill";
import { api, inboxStream, type InboxStreamEvent } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import { flagLabel } from "@/lib/format";
import type { ConsoleInfo, Flag, Preset, SendResult } from "@/lib/types";
import { useApi } from "@/lib/use-api";

import { evidence } from "./panel-inbox";

const STAGES = ["received", "extracting", "checking"];
const STAGE_LABEL: Record<string, string> = {
  received: "Received",
  extracting: "Reading in quarantine…",
  checking: "Running fraud checks…",
};

function verdictPill(v: SendResult["verdict"]) {
  if (v === "held") return <StatusPill size="sm" status="blocked" label="Held" />;
  if (v === "flagged") return <StatusPill size="sm" status="waiting" label="Check first" />;
  return <StatusPill size="sm" status="executed" label="Accepted" />;
}

/** One flag in plain language, with where it was caught: a code check or the model's reading. */
function FlagLine({ flag }: { flag: Flag }) {
  return (
    <li className="dc-flag">
      <span className="t">{flagLabel(flag.code)}</span>
      <span className="d">
        {evidence(flag) || (flag.severity === "high" ? "High risk." : "Worth a check.")}{" "}
        {flag.detected_by.includes("code") ? "Rule-based check." : "Needed the model's reading."}
      </span>
    </li>
  );
}

function ResultCard({ live, result, label }: { live?: InboxStreamEvent; result?: SendResult; label: string }) {
  const stage = live?.stage ?? "received";
  const at = STAGES.indexOf(stage);
  const rec = result?.record;
  const script = rec?.sentinel.call_script;
  return (
    <article className="dc-result" aria-live="polite">
      <header>
        <div className="who">
          <div style={{ fontWeight: 500 }}>{label}</div>
          <div className="kc-caption">{live?.subject ?? rec?.subject}</div>
        </div>
        {result ? (
          verdictPill(result.verdict)
        ) : (
          <span className="kc-caption">{STAGE_LABEL[stage] ?? "Working…"}</span>
        )}
      </header>
      <div className="ka-live__steps" aria-hidden>
        {[0, 1, 2, 3].map((i) => (
          <span key={i} className={"ka-live__step" + (result || i <= at ? " is-done" : "")} />
        ))}
      </div>
      {result ? (
        <>
          {result.expected && result.expected !== result.verdict ? (
            <div className="kc-caption" style={{ color: "var(--warning)" }}>
              Expected “{result.expected}”, got “{result.verdict}”.
            </div>
          ) : null}
          {rec && (rec.sentinel.flags ?? []).length ? (
            <ul className="dc-flags">
              {(rec.sentinel.flags ?? []).map((f, i) => (
                <FlagLine key={`${f.code}-${i}`} flag={f} />
              ))}
            </ul>
          ) : (
            <div className="kc-caption" style={{ display: "flex", gap: 6, alignItems: "center" }}>
              <ShieldCheck size={16} strokeWidth={1.5} aria-hidden /> No red flags
            </div>
          )}
          {rec && Object.values(rec.fields.extraction_status ?? {}).some((s) => s !== "ok") ? (
            <div className="kc-caption" style={{ color: "var(--warning)" }}>
              The model could not read this message, so only rule-based checks ran.
            </div>
          ) : null}
          {script ? (
            <details className="dc-script">
              <summary>Verification call script</summary>
              <ol>
                {script.lines.map((l) => (
                  <li key={l}>{l}</li>
                ))}
              </ol>
            </details>
          ) : null}
        </>
      ) : null}
    </article>
  );
}

function PresetGroup({
  title,
  presets,
  busy,
  onSend,
}: {
  title: string;
  presets: Preset[];
  busy: string | null;
  onSend: (p: Preset) => void;
}) {
  return (
    <section className="dc-group">
      <h3 className="kc-label">{title}</h3>
      <div className="dc-presets">
        {presets.map((p) => (
          <button
            key={p.key}
            type="button"
            className="dc-preset"
            disabled={!p.available || busy === p.key}
            onClick={() => onSend(p)}
          >
            <span className="l">{p.label}</span>
            <span className="d">{p.available ? p.description : p.unavailable_reason}</span>
          </button>
        ))}
      </div>
    </section>
  );
}

function CustomForm({ onSend, busy }: { onSend: (form: FormData) => void; busy: boolean }) {
  const file = useRef<HTMLInputElement>(null);
  const [fileName, setFileName] = useState("");
  return (
    <form
      className="dc-form"
      onSubmit={(ev) => {
        ev.preventDefault();
        onSend(new FormData(ev.currentTarget));
      }}
    >
      <label>
        <span className="kc-label">Sender name</span>
        <input name="sender_name" placeholder="Golden Grain Wholesale" />
      </label>
      <label>
        <span className="kc-label">Sender address</span>
        <input name="sender_email" type="email" required placeholder="accounts@lookalike.example" />
      </label>
      <label>
        <span className="kc-label">Subject</span>
        <input name="subject" placeholder="Updated remittance details" />
      </label>
      <label>
        <span className="kc-label">Message</span>
        <textarea name="body" rows={5} required />
      </label>
      <div className="dc-attach">
        <input
          ref={file}
          name="attachment"
          type="file"
          accept="application/pdf,image/png,image/jpeg"
          hidden
          onChange={(e) => setFileName(e.target.files?.[0]?.name ?? "")}
        />
        <Button variant="ghost" size="sm" iconLeft={Paperclip} onClick={() => file.current?.click()}>
          {fileName || "Attach PDF or image"}
        </Button>
      </div>
      <Button type="submit" iconLeft={Send} loading={busy}>
        Send to inbox
      </Button>
    </form>
  );
}

/**
 * The live demo console: a simulated sender for recording the demo. Mail goes into the sandbox mailbox through the
 * real quarantine and sentinel pipeline and each stage shows here as it happens. Left: this console. Right: the
 * owner's app, so both fit in one recording. Only mounted when NEXT_PUBLIC_DEMO_MODE is on (see shell.tsx).
 */
export function DemoConsole() {
  const { business } = useBusiness();
  const id = business?.id ?? "";
  const info = useApi<ConsoleInfo>(id ? `demo-console:${id}` : null, () => api.demoConsole(id));
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [live, setLive] = useState<Record<string, InboxStreamEvent>>({});
  const [results, setResults] = useState<Record<string, SendResult>>({});
  const [labels, setLabels] = useState<Record<string, string>>({});
  const [order, setOrder] = useState<string[]>([]);

  useEffect(() => {
    if (!id) return;
    const ctl = new AbortController();
    (async () => {
      try {
        for await (const { data: e } of inboxStream(id, ctl.signal)) {
          if (e.kind !== "message" || e.source !== "console" || !e.email_id) continue;
          const emailId = e.email_id;
          setLive((l) => ({ ...l, [emailId]: e }));
          setOrder((o) => (o.includes(emailId) ? o : [emailId, ...o]));
        }
      } catch {
        // Stream closed (navigation, server restart): results still arrive with each send.
      }
    })();
    return () => ctl.abort();
  }, [id]);

  const run = async (key: string, label: string, go: () => Promise<SendResult>) => {
    setBusy(key);
    setError(null);
    try {
      const r = await go();
      setResults((x) => ({ ...x, [r.email_id]: r }));
      setLabels((x) => ({ ...x, [r.email_id]: label }));
      setOrder((o) => (o.includes(r.email_id) ? o : [r.email_id, ...o]));
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(null);
    }
  };

  const presets = info.data?.presets ?? [];
  const sendPreset = (p: Preset) => run(p.key, p.label, () => api.demoSendPreset(id, p.key));
  return (
    <div className="dc">
      <section className="dc-left" aria-label="Demo console">
        <header className="dc-head">
          <FlaskConical size={20} strokeWidth={1.5} aria-hidden />
          <div>
            <h1>Demo console</h1>
            <div className="kc-caption">Simulated sender · {business?.name ?? "no business"}</div>
          </div>
          <Badge variant="outline">Simulated</Badge>
        </header>
        <AlertBanner variant="info" eyebrow="Demo tool">
          Nothing here sends real email. Messages land in the sandbox inbox and are read by a live model, then
          checked, just like real mail.
        </AlertBanner>
        {error || info.error ? (
          <AlertBanner variant="fraud" eyebrow="Could not send">
            {error ?? errorMessage(info.error)}
          </AlertBanner>
        ) : null}
        <PresetGroup
          title="Normal mail"
          presets={presets.filter((p) => p.group === "normal")}
          busy={busy}
          onSend={sendPreset}
        />
        <PresetGroup
          title="Attacks"
          presets={presets.filter((p) => p.group === "attack")}
          busy={busy}
          onSend={sendPreset}
        />
        <section className="dc-group">
          <h3 className="kc-label">Compose your own</h3>
          <CustomForm
            busy={busy === "custom"}
            onSend={(form) => run("custom", "Custom email", () => api.demoSendCustom(id, form))}
          />
        </section>
        <section className="dc-group">
          <h3 className="kc-label">Live results</h3>
          {order.length ? (
            <div className="dc-results">
              {order.map((eid) => (
                <ResultCard
                  key={eid}
                  live={live[eid]}
                  result={results[eid]}
                  label={labels[eid] ?? live[eid]?.sender ?? "Email"}
                />
              ))}
            </div>
          ) : (
            <div className="kc-caption">Send an email to watch it go through the checks.</div>
          )}
        </section>
        {info.data ? (
          <details className="dc-checks">
            <summary>
              <ShieldAlert size={16} strokeWidth={1.5} aria-hidden /> Which checks need the model
            </summary>
            <p className="kc-caption">If the model is unreachable, these still catch fraud and hold the message:</p>
            <ul>
              {info.data.rule_based_checks.map((c) => (
                <li key={c}>{c}</li>
              ))}
            </ul>
            <p className="kc-caption">These need the model to read amounts, accounts and numbers first:</p>
            <ul>
              {info.data.model_assisted_checks.map((c) => (
                <li key={c}>{c}</li>
              ))}
            </ul>
          </details>
        ) : null}
      </section>
      <iframe className="dc-right" src="/inbox" title="The owner's app" />
    </div>
  );
}
