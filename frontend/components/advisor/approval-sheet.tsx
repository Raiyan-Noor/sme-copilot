"use client";

import { ArrowLeft, CircleCheck, Mail, Pencil, PenLine, Phone, ShieldAlert, UserPlus } from "lucide-react";
import { useCallback, useState } from "react";

import { useBusiness } from "@/components/business-context";
import { Badge } from "@/components/kc/badge";
import { Button } from "@/components/kc/button";
import { TraceScope, type FactRef } from "@/components/kc/fact";
import { Sheet } from "@/components/kc/sheet";
import { StatusPill } from "@/components/kc/status-pill";
import { Skeleton } from "@/components/ui/skeleton";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import { money, reasonLabel, ruleLabel, sentence, shortDate, toolTitle } from "@/lib/format";
import { ensureEnrolled, signMessage } from "@/lib/owner-key";
import type { ApprovalView, Decision, EmailView } from "@/lib/types";
import { useApi } from "@/lib/use-api";

import { useAdvisor } from "./state";
import { TraceView } from "./trace-view";

function argValue(key: string, value: unknown, currency: string): string {
  if (typeof value === "number" && key.endsWith("_minor")) return money(value, currency);
  if (value === null || value === undefined) return "none";
  return String(value);
}

const ORIGIN: Record<string, string> = {
  planner: "Written by the assistant",
  overnight: "Drafted overnight from your records",
  owner: "Written by you",
};

/**
 * The email the owner signs: recipient, subject and the full body exactly as stored, and why it was prepared. The
 * owner can edit the draft; every number in an assistant-written body was rendered from a fact in your records.
 */
function EmailSection({
  email,
  editing,
  onEdit,
}: {
  email: EmailView;
  editing: { subject: string; body: string } | null;
  onEdit: (e: { subject: string; body: string } | null) => void;
}) {
  return (
    <section className="ka-sec" style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      <h3 className="kc-label" style={{ color: "var(--text-muted)", display: "flex", gap: 8, alignItems: "center" }}>
        <Mail size={16} strokeWidth={1.5} aria-hidden /> The email
      </h3>
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
        <Badge variant="neutral">{ORIGIN[email.origin] ?? email.origin}</Badge>
        {email.edited ? <Badge variant="brand">Edited by you</Badge> : null}
        {email.added_by_owner ? (
          <Badge variant="neutral" icon={UserPlus}>
            New address you added
          </Badge>
        ) : null}
      </div>
      <dl className="ka-tx-detail">
        <dt>To</dt>
        <dd>
          {email.recipient_name}
          {email.recipient_email ? <span className="kc-caption"> · {email.recipient_email}</span> : null}
        </dd>
        <dt>Why</dt>
        <dd>{email.reason}</dd>
      </dl>
      {editing ? (
        <div className="ka-mailform">
          <input
            value={editing.subject}
            maxLength={120}
            onChange={(e) => onEdit({ ...editing, subject: e.target.value })}
            aria-label="Subject"
          />
          <textarea
            value={editing.body}
            maxLength={2000}
            onChange={(e) => onEdit({ ...editing, body: e.target.value })}
            aria-label="Message"
          />
          <p className="kc-caption">
            These are your words, so check any amount or date you type. The assistant&apos;s numbers come from your
            records; yours do not.
          </p>
        </div>
      ) : (
        <>
          <div className="ka-text">
            <strong>{email.subject}</strong>
          </div>
          <div className="ka-mailbody">{email.body}</div>
          <div>
            <Button
              size="sm"
              variant="ghost"
              iconLeft={Pencil}
              onClick={() => onEdit({ subject: email.subject, body: email.body })}
            >
              Edit the draft
            </Button>
          </div>
        </>
      )}
    </section>
  );
}

/**
 * The approval sheet: everything the owner signs, shown exactly as the gateway stored it. Signing happens here, in
 * the browser, with the key from IndexedDB (invariant 6): the server's canonical `message` for the payload
 * {action, args_hash, nonce, expiry} is signed with tweetnacl and only the signature and public key are sent. The
 * result shown is the gateway's decision, never an assumption that it worked (invariant 1).
 */
export function ApprovalSheet() {
  const { approval, openApproval, closeApproval, resolve, resolved, addPending, toast } = useAdvisor();
  const { business, session } = useBusiness();
  const id = business?.id ?? "";
  const approvalId = approval?.approvalId ?? null;
  const view = useApi<ApprovalView>(approvalId && id ? `approval:${session}:${id}:${approvalId}` : null, () =>
    api.approval(id, approvalId as string),
  );
  const [traceFact, setTraceFact] = useState<FactRef | null>(null);
  const [signing, setSigning] = useState(false);
  const [called, setCalled] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [decision, setDecision] = useState<Decision | null>(null);
  const [editing, setEditing] = useState<{ subject: string; body: string } | null>(null);
  const [saving, setSaving] = useState(false);

  const close = useCallback(() => {
    setEditing(null);
    setTraceFact(null);
    setError(null);
    setDecision(null);
    setCalled(false);
    closeApproval();
  }, [closeApproval]);

  if (!approval) return null;
  const v = view.data;
  const currency = business?.currency ?? "USD";
  const alreadyDecided = v && v.status !== "pending";
  const needsCall = !!v?.requires_out_of_band_call_script;
  const untrusted = v?.reasons.filter((r) => r.startsWith("untrusted_provenance:")) ?? [];

  const sign = async () => {
    if (!v) return;
    setSigning(true);
    setError(null);
    try {
      await ensureEnrolled(id);
      const { signature, publicKey } = await signMessage(v.message);
      const d = await api.approve(id, v.approval_id, {
        signature,
        public_key: publicKey,
        out_of_band_confirmed: needsCall ? called : false,
      });
      if (d.status === "executed") {
        setDecision(d);
        resolve(v.approval_id, "executed", d);
        toast({ variant: "success", title: "Signed and done", description: toolTitle(v.tool) });
      } else {
        resolve(v.approval_id, "denied");
        setError(`The gateway refused it: ${ruleLabel(d.rule ?? "denied")}.`);
      }
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setSigning(false);
    }
  };

  // Editing an email replaces the approval: the new text is a new draft with a new payload, so a signature for the old
  // text can never send the new one. The sheet moves to the new approval.
  const saveEdit = async () => {
    if (!v || !editing) return;
    setSaving(true);
    setError(null);
    try {
      const d = await api.reviseEmail(id, v.approval_id, editing);
      if (d.status === "pending_approval" && d.approval) {
        resolve(v.approval_id, "superseded");
        addPending([d.approval.approval_id]);
        setEditing(null);
        openApproval({ approvalId: d.approval.approval_id, context: approval?.context });
        toast({ title: "Draft updated", description: "Read it once more, then sign." });
      } else {
        setError(`The change was not accepted: ${ruleLabel(d.rule ?? "denied")}.`);
      }
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setSaving(false);
    }
  };

  const decline = () => {
    if (v) resolve(v.approval_id, "declined");
    toast({ title: "Declined", description: "Nothing was sent." });
    close();
  };

  const footer = traceFact ? null : editing ? (
    <>
      <Button
        iconLeft={PenLine}
        loading={saving}
        disabled={!editing.subject.trim() || !editing.body.trim()}
        onClick={saveEdit}
      >
        Save changes
      </Button>
      <Button variant="secondary" onClick={() => setEditing(null)} disabled={saving}>
        Keep the original
      </Button>
    </>
  ) : decision ? (
    <Button variant="secondary" onClick={close}>
      Done
    </Button>
  ) : (
    <>
      <Button
        iconLeft={PenLine}
        loading={signing}
        disabled={!v || !!alreadyDecided || !!resolved[approval.approvalId] || (needsCall && !called)}
        onClick={sign}
      >
        {signing ? "Signing…" : "Sign and approve"}
      </Button>
      <Button variant="secondary" onClick={decline} disabled={signing || !!alreadyDecided}>
        Decline
      </Button>
    </>
  );

  return (
    <Sheet
      open
      onClose={close}
      title={traceFact ? "Where this number comes from" : v ? toolTitle(v.tool) : "Approval"}
      description={traceFact ? undefined : "Check every line. You sign exactly this."}
      footer={footer}
    >
      <TraceScope value={setTraceFact}>
        {traceFact ? (
          <div className="ka-stack" style={{ gap: 16 }}>
            <div>
              <Button variant="ghost" size="sm" iconLeft={ArrowLeft} onClick={() => setTraceFact(null)}>
                Back to the approval
              </Button>
            </div>
            <TraceView fact={traceFact} />
          </div>
        ) : view.error !== undefined ? (
          <p className="ka-text" style={{ color: "var(--danger)" }}>
            Could not load this approval: {errorMessage(view.error)}
          </p>
        ) : !v ? (
          <Skeleton className="h-64 w-full" />
        ) : decision ? (
          <div className="ka-mandate" role="status">
            <div className="ka-mandate__top">
              <div className="ka-mandate__title">
                <CircleCheck size={18} strokeWidth={1.5} style={{ color: "var(--success)" }} aria-hidden />
                Signed
              </div>
              <StatusPill status="executed" size="sm" />
            </div>
            <dl>
              <dt>Mandate ID</dt>
              <dd className="ka-mandate__id">{decision.mandate_id ?? "not issued"}</dd>
              <dt>Action</dt>
              <dd>{toolTitle(v.tool)}</dd>
              <dt>Signed with</dt>
              <dd>The key on this device</dd>
              <dt>Record</dt>
              <dd>Signature and result are in the audit log</dd>
            </dl>
          </div>
        ) : (
          <div className="ka-stack" style={{ gap: 24 }}>
            {alreadyDecided ? (
              <p className="ka-text" style={{ color: "var(--text-muted)" }}>
                This approval is {v.status}. Nothing more to sign.
              </p>
            ) : null}
            {approval.context ? <div className="ka-text">{approval.context}</div> : null}

            {v.email ? (
              <EmailSection email={v.email} editing={editing} onEdit={setEditing} />
            ) : (
              <section className="ka-sec">
                <h3 className="kc-label" style={{ color: "var(--text-muted)" }}>
                  The details
                </h3>
                <dl className="kc-approval__facts">
                  {Object.entries(v.args).map(([k, val]) => (
                    <div key={k} className="kc-approval__fact">
                      <dt>{sentence(k.replace(/_minor$/, ""))}</dt>
                      <dd style={{ overflowWrap: "anywhere" }}>{argValue(k, val, currency)}</dd>
                    </div>
                  ))}
                </dl>
              </section>
            )}

            {untrusted.length > 0 ? (
              <section className="kc-alert kc-alert--fraud">
                <span className="kc-alert__icon">
                  <ShieldAlert size={20} strokeWidth={1.5} aria-hidden />
                </span>
                <div className="kc-alert__content">
                  <div className="kc-alert__eyebrow">Risk</div>
                  {untrusted.map((r) => (
                    <div key={r} className="kc-alert__body">
                      {reasonLabel(r)}
                    </div>
                  ))}
                </div>
              </section>
            ) : null}

            <section className="ka-sec">
              <h3 className="kc-label" style={{ color: "var(--text-muted)" }}>
                Why it needs you
              </h3>
              {v.reasons
                .filter((r) => !r.startsWith("untrusted_provenance:"))
                .map((r) => (
                  <p key={r} className="ka-text">
                    {reasonLabel(r)}
                  </p>
                ))}
            </section>

            {needsCall ? (
              <label className="ka-callnum" style={{ cursor: "pointer" }}>
                <Phone size={20} strokeWidth={1.5} style={{ color: "var(--brand-primary)" }} aria-hidden />
                <span style={{ flex: 1 }} className="ka-text">
                  I called them on a number I already had, not one from the email, and they confirmed the change.
                </span>
                <input type="checkbox" checked={called} onChange={(e) => setCalled(e.target.checked)} />
              </label>
            ) : null}

            <section className="ka-sec">
              <h3 className="kc-label" style={{ color: "var(--text-muted)" }}>
                What you sign
              </h3>
              <dl
                className="ka-mail__hdr"
                style={{
                  borderBottom: 0,
                  paddingBottom: 0,
                  fontFamily: "var(--font-code)",
                  gridTemplateColumns: "88px minmax(0,1fr)",
                }}
              >
                <dt>action</dt>
                <dd>{v.payload.action}</dd>
                <dt>args_hash</dt>
                <dd>{v.payload.args_hash}</dd>
                <dt>nonce</dt>
                <dd>{v.payload.nonce}</dd>
                <dt>expiry</dt>
                <dd>{shortDate(v.payload.expiry)}</dd>
              </dl>
            </section>

            {error ? (
              <p className="ka-text" style={{ color: "var(--danger)" }} role="alert">
                {error}
              </p>
            ) : null}
          </div>
        )}
      </TraceScope>
    </Sheet>
  );
}
