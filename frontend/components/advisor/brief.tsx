"use client";

import { Ban, ChevronRight, CircleCheck, CircleSlash, FastForward, MessageSquare } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { useBusinessKey } from "@/components/business-context";
import { AlertBanner } from "@/components/kc/alert-banner";
import { ApprovalCard } from "@/components/kc/approval-card";
import { Badge } from "@/components/kc/badge";
import { Button } from "@/components/kc/button";
import { Card } from "@/components/kc/card";
import { ChatBubble } from "@/components/kc/chat-bubble";
import { FactNumber, FactText } from "@/components/kc/fact";
import { StatusPill, decisionPill, type PillStatus } from "@/components/kc/status-pill";
import { api, ApiError } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import { flagLabel, reasonLabel, ruleLabel, toolTitle } from "@/lib/format";
import type { DoneItem, InboxItem, MorningBrief, NeedsYouItem } from "@/lib/types";
import { useApi } from "@/lib/use-api";
import { cn } from "@/lib/utils";

import { useFastForward } from "./fast-forward";
import { useAdvisor, type Resolution } from "./state";

const RESOLVED: Record<Resolution, { status: PillStatus; note: string }> = {
  executed: { status: "executed", note: "Signed by you. The result is in the audit log." },
  denied: { status: "blocked", note: "The gateway refused it. Nothing was sent." },
  declined: { status: "blocked", note: "Declined. Nothing was sent." },
};

export function Resolved({
  icon: Icon,
  tone,
  children,
}: {
  icon: typeof Ban;
  tone: string;
  children: React.ReactNode;
}) {
  return (
    <div className="ka-resolved">
      <span className="i" style={{ color: tone }}>
        <Icon size={18} strokeWidth={1.5} aria-hidden />
      </span>
      <span>{children}</span>
    </div>
  );
}

/**
 * The Morning Brief: the day opens as the advisor's first message (GET /brief, written by the overnight job), with
 * what needs the owner attached to it. Prose carries {fact:id} placeholders; every figure is a FactNumber.
 */
export function BriefMessage() {
  const { id, key } = useBusinessKey("brief");
  const brief = useApi<MorningBrief>(key, () => api.brief(id));
  const inbox = useApi(key && `${key}:inbox`, () => api.inbox(id));
  const ff = useFastForward();

  if (brief.error instanceof ApiError && brief.error.status === 404) {
    return (
      <ChatBubble
        role="copilot"
        name="Morning brief"
        attachment={
          <div>
            <Button variant="secondary" size="sm" iconLeft={FastForward} loading={ff.busy} onClick={ff.run}>
              Fast-forward to tomorrow 7:00
            </Button>
          </div>
        }
      >
        No brief yet for today. Fast-forward to tomorrow morning and I will run the overnight checks and write one.
      </ChatBubble>
    );
  }
  if (brief.error !== undefined) {
    return (
      <ChatBubble role="copilot" name="Morning brief">
        <span className="kc-caption">I could not load the brief: {errorMessage(brief.error)}</span>
      </ChatBubble>
    );
  }
  if (!brief.data) {
    return (
      <ChatBubble role="copilot" name="Morning brief">
        <span className="kc-caption">Reading your accounts…</span>
      </ChatBubble>
    );
  }
  const held = inbox.data?.items.filter((i) => i.record.sentinel.hold) ?? [];
  return <Brief brief={brief.data} held={held} />;
}

function Brief({ brief, held }: { brief: MorningBrief; held: InboxItem[] }) {
  const { addPending, scrollRequest } = useAdvisor();
  const anchor = useRef<HTMLDivElement>(null);

  useEffect(() => {
    addPending(brief.needs_you.map((n) => n.approval_id));
  }, [brief, addPending]);

  useEffect(() => {
    if (scrollRequest === 0) return;
    const t = setTimeout(() => anchor.current?.scrollIntoView({ behavior: "smooth", block: "start" }), 80);
    return () => clearTimeout(t);
  }, [scrollRequest]);

  return (
    <ChatBubble
      role="copilot"
      name={
        <>
          Morning brief · <FactNumber fact={brief.as_of} />
        </>
      }
      attachment={
        <div className="ka-attach" ref={anchor} style={{ scrollMarginTop: 24 }}>
          {held.map((item) => (
            <HeldAlert key={item.record.email_id} item={item} />
          ))}
          {brief.needs_you.map((n) => (
            <NeedsYou key={n.approval_id} item={n} brief={brief} />
          ))}
          {brief.improve ? <Improve brief={brief} /> : null}
          <Overnight done={brief.done_overnight} notDone={brief.not_done} facts={brief.facts} />
        </div>
      }
    >
      {brief.paragraphs.map((p, i) => (
        <span key={i} className="ka-p">
          <FactText text={p} facts={brief.facts} />
        </span>
      ))}
    </ChatBubble>
  );
}

function HeldAlert({ item }: { item: InboxItem }) {
  const { pushPanel, toast } = useAdvisor();
  const [kept, setKept] = useState(false);
  const r = item.record;
  const sender = r.from_display_name || r.from_address;
  const flags = r.sentinel.flags ?? [];
  if (kept) {
    return (
      <Resolved icon={Ban} tone="var(--danger)">
        Nothing from {sender}&apos;s message will be paid. It stays held until you check with them.
      </Resolved>
    );
  }
  return (
    <AlertBanner
      className="ka-fraud"
      variant="fraud"
      title={`${sender}: ${flags.length ? flagLabel(flags[0].code).toLowerCase() : "held for review"}`}
      actions={
        <>
          <Button
            variant="destructive"
            size="sm"
            iconLeft={Ban}
            onClick={() => {
              setKept(true);
              toast({ variant: "danger", title: "Payment stays blocked", description: sender });
            }}
          >
            Keep payment blocked
          </Button>
          <Button variant="secondary" size="sm" onClick={() => pushPanel({ view: "email", emailId: r.email_id })}>
            Review email
          </Button>
        </>
      }
    >
      {flags.length > 1 ? `${flags.map((f) => flagLabel(f.code)).join(". ")}. ` : ""}I held this message, so nothing in
      it can be paid until you check with them.
    </AlertBanner>
  );
}

function NeedsYou({ item, brief }: { item: NeedsYouItem; brief: MorningBrief }) {
  const { openApproval, resolved, resolve, toast } = useAdvisor();
  const how = resolved[item.approval_id];
  const summary = <FactText text={item.summary} facts={brief.facts} />;
  return (
    <ApprovalCard
      status={how ? RESOLVED[how].status : "waiting"}
      title={toolTitle(item.tool)}
      description={summary}
      limitNote={item.reasons.map(reasonLabel).join(" ")}
      resolvedNote={how ? RESOLVED[how].note : undefined}
      onApprove={() => openApproval({ approvalId: item.approval_id, context: summary })}
      onDecline={() => {
        resolve(item.approval_id, "declined");
        toast({ title: "Declined", description: "Nothing was sent." });
      }}
    />
  );
}

function Improve({ brief }: { brief: MorningBrief }) {
  const { send } = useAdvisor();
  const [state, setState] = useState<"open" | "asked" | "skipped">("open");
  const imp = brief.improve!;
  if (state === "skipped") {
    return (
      <Resolved icon={CircleSlash} tone="var(--text-muted)">
        Kept as it is. I will check again tomorrow.
      </Resolved>
    );
  }
  return (
    <Card
      variant="improve"
      padding="md"
      title={imp.title}
      description={<FactText text={imp.text} facts={imp.facts} />}
      action={
        <Badge variant="savings">
          Saves <FactNumber fact={imp.yearly_saving} />
        </Badge>
      }
      footer={
        <div className="ka-improve-foot">
          <Button
            variant="secondary"
            size="sm"
            iconLeft={MessageSquare}
            disabled={state === "asked"}
            onClick={() => {
              setState("asked");
              send(`How can I fix this: ${imp.title}?`);
            }}
          >
            Ask how to fix it
          </Button>
          <Button variant="ghost" size="sm" onClick={() => setState("skipped")}>
            Not now
          </Button>
        </div>
      }
    />
  );
}

function Overnight({ done, notDone, facts }: { done: DoneItem[]; notDone: DoneItem[]; facts: MorningBrief["facts"] }) {
  const [open, setOpen] = useState(false);
  const items = [...done, ...notDone];
  if (items.length === 0) return null;
  const n = done.filter((d) => d.status === "executed").length;
  return (
    <div>
      <button
        type="button"
        className={cn("ka-fold", open && "is-open")}
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
      >
        <span className="ok">
          <CircleCheck size={18} strokeWidth={1.5} aria-hidden />
        </span>
        <span>
          {n === 0
            ? "Nothing ran overnight"
            : n === 1
              ? "I handled one thing overnight"
              : `I handled ${n} things overnight`}
          {notDone.length ? ", and held back what your limits do not cover" : ""}
        </span>
        <span className="chev">
          <ChevronRight size={16} strokeWidth={1.5} aria-hidden />
        </span>
      </button>
      {open ? (
        <ul className="ka-foldlist">
          {items.map((o, i) => (
            <li key={i}>
              <span className="w">
                <span>
                  <FactText text={o.summary} facts={facts} />
                </span>
                <span className="kc-caption">
                  <FactNumber fact={o.date} />
                  {o.rule ? ` · ${ruleLabel(o.rule)}` : ""}
                </span>
              </span>
              <StatusPill
                status={decisionPill(o.status)}
                size="sm"
                label={o.status === "skipped" ? "Skipped" : undefined}
              />
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
