"use client";

import { ChevronDown, ChevronRight, Mail, PenLine, Plus, ShieldCheck, UserPlus } from "lucide-react";
import { useState } from "react";

import { useBusinessKey } from "@/components/business-context";
import { Badge } from "@/components/kc/badge";
import { Button } from "@/components/kc/button";
import { StatusPill } from "@/components/kc/status-pill";
import { Skeleton } from "@/components/ui/skeleton";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import { ruleLabel, shortDate } from "@/lib/format";
import type { OutboxEmail, WaitingEmail } from "@/lib/types";
import { useApi } from "@/lib/use-api";

import { PanelFrame } from "./detail-panel";
import { useAdvisor } from "./state";

const ORIGIN: Record<string, string> = {
  planner: "Written by the assistant",
  overnight: "Drafted overnight",
  owner: "Written by you",
};

/** Where an email went: really sent through the connected Gmail, or kept in the simulated outbox (with the reason). */
function Transport({ mail }: { mail: OutboxEmail }) {
  return mail.transport === "gmail" ? (
    <StatusPill size="sm" status="executed" label="Sent with Gmail" />
  ) : (
    <StatusPill size="sm" status="neutral" label="Simulated" />
  );
}

function Waiting({ item }: { item: WaitingEmail }) {
  const { openApproval } = useAdvisor();
  const m = item.email;
  return (
    <article className="ka-gmail" style={{ gap: 8 }}>
      <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
        <StatusPill size="sm" status="waiting" label="Waiting for you" />
        <Badge variant="neutral">{ORIGIN[m.origin] ?? m.origin}</Badge>
        {m.added_by_owner ? <Badge variant="neutral">New address you added</Badge> : null}
        <span className="kc-caption" style={{ marginLeft: "auto" }}>
          Expires {shortDate(item.expires)}
        </span>
      </div>
      <div className="ka-text">
        <strong>To {m.recipient_name || "a contact"}</strong>
        {m.recipient_email ? <span className="kc-caption"> · {m.recipient_email}</span> : null}
      </div>
      <div className="ka-text">{m.subject}</div>
      <div>
        <Button size="sm" iconLeft={PenLine} onClick={() => openApproval({ approvalId: item.approval_id })}>
          Read, edit and sign
        </Button>
      </div>
    </article>
  );
}

function Sent({ mail }: { mail: OutboxEmail }) {
  const [open, setOpen] = useState(false);
  const Chevron = open ? ChevronDown : ChevronRight;
  return (
    <li className="ka-gmail" style={{ gap: 8, listStyle: "none" }}>
      <button
        type="button"
        className="ka-nav"
        style={{ justifyContent: "flex-start", gap: 10, textAlign: "left", height: "auto", padding: 0 }}
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
      >
        <Chevron size={16} strokeWidth={1.5} aria-hidden />
        <span style={{ flex: 1, minWidth: 0 }}>
          <span className="ka-text" style={{ display: "block", overflowWrap: "anywhere" }}>
            <strong>{mail.recipient_name || "A contact"}</strong> · {mail.subject || "Message"}
          </span>
          <span className="kc-caption">{shortDate(mail.on_date)}</span>
        </span>
        <Transport mail={mail} />
      </button>
      {open ? (
        <div className="ka-stack" style={{ gap: 12 }}>
          {mail.body ? <div className="ka-mailbody">{mail.body}</div> : null}
          <dl className="ka-tx-detail">
            <dt>To</dt>
            <dd>{mail.recipient_email ?? mail.recipient_name}</dd>
            {mail.origin ? (
              <>
                <dt>Written</dt>
                <dd>{ORIGIN[mail.origin] ?? mail.origin}</dd>
              </>
            ) : null}
            <dt>Result</dt>
            <dd>{mail.transport === "gmail" ? "Sent with your connected Gmail" : (mail.label ?? "Simulated")}</dd>
            <dt>Reference</dt>
            <dd style={{ fontFamily: "var(--font-code)" }}>{mail.ref}</dd>
          </dl>
        </div>
      ) : null}
    </li>
  );
}

const NEW = "__new__";

/** The owner writes an email. It becomes a draft and a pending approval; nothing leaves until they sign it. */
function Compose({ businessId, onDone }: { businessId: string; onDone: () => void }) {
  const { openApproval, addPending, toast } = useAdvisor();
  const contacts = useApi(`email-contacts:${businessId}`, () => api.emailContacts(businessId));
  const [to, setTo] = useState("");
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [again, setAgain] = useState("");
  const [known, setKnown] = useState(false);
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fresh = to === NEW;
  const ready = subject.trim() && body.trim() && (fresh ? name.trim() && email && again && known : to);

  const prepare = async () => {
    setBusy(true);
    setError(null);
    try {
      let recipient = to;
      if (fresh) {
        const added = await api.addEmailRecipient(businessId, {
          name,
          email,
          confirm_email: again,
          confirmed: known,
        });
        recipient = added.id;
      }
      const d = await api.composeEmail(businessId, { recipient_id: recipient, subject, body });
      if (d.status === "pending_approval" && d.approval) {
        addPending([d.approval.approval_id]);
        toast({ title: "Ready to sign", description: "Read it once more, then sign." });
        onDone();
        openApproval({ approvalId: d.approval.approval_id });
      } else {
        setError(`Not prepared: ${ruleLabel(d.rule ?? "denied")}.`);
      }
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="ka-gmail ka-mailform" style={{ gap: 10 }}>
      <div className="kc-label">New email</div>
      <select value={to} onChange={(e) => setTo(e.target.value)} aria-label="Send to">
        <option value="">Choose who it goes to</option>
        {(contacts.data ?? []).map((c) => (
          <option key={c.id} value={c.id}>
            {c.name} ({c.email})
          </option>
        ))}
        <option value={NEW}>A new address…</option>
      </select>
      {fresh ? (
        <div className="ka-mailform">
          <input placeholder="Their name" value={name} maxLength={60} onChange={(e) => setName(e.target.value)} aria-label="Their name" />
          <input
            placeholder="Email address"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            aria-label="Email address"
            autoComplete="off"
          />
          <input
            placeholder="Email address again"
            value={again}
            onChange={(e) => setAgain(e.target.value)}
            onPaste={(e) => e.preventDefault()}
            aria-label="Email address again"
            autoComplete="off"
          />
          <label className="ka-callnum" style={{ cursor: "pointer" }}>
            <UserPlus size={20} strokeWidth={1.5} style={{ color: "var(--brand-primary)" }} aria-hidden />
            <span style={{ flex: 1 }} className="ka-text">
              I know this address and want to email it. It is not one of my saved contacts, and I did not copy it from an
              email.
            </span>
            <input type="checkbox" checked={known} onChange={(e) => setKnown(e.target.checked)} />
          </label>
        </div>
      ) : null}
      <input placeholder="Subject" value={subject} maxLength={120} onChange={(e) => setSubject(e.target.value)} aria-label="Subject" />
      <textarea placeholder="Write your message" value={body} maxLength={2000} onChange={(e) => setBody(e.target.value)} aria-label="Message" />
      {error ? (
        <p className="ka-text" style={{ color: "var(--danger)" }} role="alert">
          {error}
        </p>
      ) : null}
      <div style={{ display: "flex", gap: 8 }}>
        <Button size="sm" iconLeft={PenLine} loading={busy} disabled={!ready} onClick={prepare}>
          Prepare for signing
        </Button>
        <Button size="sm" variant="ghost" onClick={onDone}>
          Cancel
        </Button>
      </div>
    </section>
  );
}

/**
 * Outbox: emails waiting for the owner's signature and everything that went out. Every email, whoever wrote it, is a
 * draft the owner reads and signs (invariants 1 and 6); this panel never sends anything itself.
 */
export function OutboxPanel() {
  const { id, key } = useBusinessKey("outbox");
  const { waiting } = useAdvisor();
  const res = useApi(key ? `${key}:${waiting}` : null, () => api.outbox(id));
  const [writing, setWriting] = useState(false);
  const data = res.data;
  return (
    <PanelFrame
      title="Outbox"
      description="Emails the assistant prepared and what went out. Nothing is sent until you read it and sign."
      footer={
        !writing ? (
          <Button variant="secondary" iconLeft={Plus} onClick={() => setWriting(true)}>
            Write an email
          </Button>
        ) : null
      }
    >
      {res.error !== undefined && !data ? (
        <p className="ka-text" style={{ color: "var(--danger)" }}>
          Could not load the outbox: {errorMessage(res.error)}
        </p>
      ) : !data ? (
        <Skeleton className="h-64 w-full" />
      ) : (
        <div className="ka-stack" style={{ gap: 24 }}>
          {writing ? (
            <Compose
              businessId={id}
              onDone={() => {
                setWriting(false);
                res.reload();
              }}
            />
          ) : null}
          <section className="ka-sec">
            <h3 className="kc-label" style={{ color: "var(--text-muted)" }}>
              Waiting for your signature
            </h3>
            {data.waiting.length ? (
              <div className="ka-stack" style={{ gap: 10 }}>
                {data.waiting.map((w) => (
                  <Waiting key={w.approval_id} item={w} />
                ))}
              </div>
            ) : (
              <p className="ka-text" style={{ color: "var(--text-muted)" }}>
                No emails are waiting for you.
              </p>
            )}
          </section>
          <section className="ka-sec">
            <h3 className="kc-label" style={{ color: "var(--text-muted)" }}>
              Sent
            </h3>
            {data.sent.length ? (
              <ul className="ka-stack" style={{ gap: 10, margin: 0, padding: 0 }}>
                {data.sent.map((m) => (
                  <Sent key={m.id} mail={m} />
                ))}
              </ul>
            ) : (
              <p className="ka-text" style={{ color: "var(--text-muted)" }}>
                <Mail size={16} strokeWidth={1.5} style={{ verticalAlign: "-3px" }} aria-hidden /> Nothing has been sent
                yet.
              </p>
            )}
          </section>
          <p className="kc-caption" style={{ display: "flex", gap: 8, alignItems: "flex-start" }}>
            <ShieldCheck size={16} strokeWidth={1.5} aria-hidden style={{ flex: "none", marginTop: 2 }} />
            <span>
              Emails go only to people in your contacts or an address you confirmed yourself, never to the sender of a
              message that was flagged, and every number in an email the assistant wrote traces to your records.
            </span>
          </p>
        </div>
      )}
    </PanelFrame>
  );
}
