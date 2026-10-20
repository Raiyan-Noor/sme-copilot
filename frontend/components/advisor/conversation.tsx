"use client";

import { ArrowRight, ArrowUp, PenLine, Repeat } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { Logo } from "@/components/brand/Logo";
import { useBusinessKey } from "@/components/business-context";
import { ApprovalCard } from "@/components/kc/approval-card";
import { Button } from "@/components/kc/button";
import { ChatBubble } from "@/components/kc/chat-bubble";
import { Segments } from "@/components/kc/fact";
import { StatusPill, decisionPill } from "@/components/kc/status-pill";
import { APP_NAME } from "@/config/app";
import { api } from "@/lib/api";
import { ruleLabel, sentence, toolTitle } from "@/lib/format";
import type { ActionEvent, BriefActivity, Decision } from "@/lib/types";
import { useApi } from "@/lib/use-api";

import { BriefMessage } from "./brief";
import { RevealSegments, StageLine } from "./stage-line";
import { useAdvisor, type Msg } from "./state";

/** Owner questions with recorded replays (tests/benign), so the chips also work in replay mode. */
const SUGGESTIONS = [
  "How much cash do I have right now?",
  "Am I going to run short of cash in the next month?",
  "Who owes me money, and how late are they?",
  "Am I wasting money anywhere?",
];
const EMPTY_SUGGESTIONS = [
  ...SUGGESTIONS,
  "How did last month go? Give me the profit and loss.",
  "What bills are coming up in the next two weeks?",
];

function Composer({
  onSend,
  autoFocus,
  disabled,
}: {
  onSend: (t: string) => void;
  autoFocus?: boolean;
  disabled?: boolean;
}) {
  const [text, setText] = useState("");
  return (
    <form
      className="ka-compose"
      onSubmit={(e) => {
        e.preventDefault();
        if (text.trim() && !disabled) {
          onSend(text.trim());
          setText("");
        }
      }}
    >
      <input
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder="Ask about your money"
        aria-label="Message"
        autoFocus={autoFocus}
        maxLength={2000}
      />
      <Button type="submit" size="sm" iconLeft={ArrowUp} aria-label="Send" disabled={!text.trim() || disabled} />
    </form>
  );
}

/**
 * An action from the gateway, inline in a reply: Executed, Waiting for your approval, or Blocked with the rule that
 * fired. The status is the gateway's decision event, never the planner's words about it (invariant 1).
 */
function ActionCard({ action }: { action: ActionEvent }) {
  const { openApproval, resolved, resolve, toast } = useAdvisor();
  const how = action.approval_id ? resolved[action.approval_id] : undefined;
  const status = how === "executed" ? "executed" : how ? "blocked" : decisionPill(action.status);
  const segments = action.reason_segments ?? [];
  const untrusted = action.untrusted_args ?? [];
  const description = segments.length ? <Segments segments={segments} /> : action.reason;
  const limitNote =
    action.status === "denied" ? (
      <>Blocked by a rule: {ruleLabel(action.rule ?? "denied")}</>
    ) : action.status === "executed" ? (
      "Done within the limit you signed."
    ) : untrusted.length ? (
      `Values from an email or upload (${untrusted.map(sentence).join(", ").toLowerCase()}), so it waits for your signature.`
    ) : (
      "Waits for your signature on the exact details."
    );
  return (
    <ApprovalCard
      status={status}
      title={toolTitle(action.tool)}
      description={description}
      limitNote={limitNote}
      meta={action.effective_tier ?? undefined}
      resolvedNote={how === "executed" ? "Signed by you." : how ? "Nothing was sent." : undefined}
      onApprove={
        action.status === "pending_approval" && action.approval_id
          ? () => openApproval({ approvalId: action.approval_id!, context: description })
          : undefined
      }
      onDecline={
        action.status === "pending_approval" && action.approval_id
          ? () => {
              resolve(action.approval_id!, "declined");
              toast({ title: "Declined", description: "Nothing was sent." });
            }
          : undefined
      }
    />
  );
}

function SignedMandate({ decision }: { decision: Decision }) {
  const { openPanel } = useAdvisor();
  return (
    <div className="ka-mandate">
      <div className="ka-mandate__top">
        <div className="ka-mandate__title">
          <PenLine size={18} strokeWidth={1.5} style={{ color: "var(--success)" }} aria-hidden />
          Mandate signed
        </div>
        <StatusPill status={decisionPill(decision.status)} size="sm" />
      </div>
      <dl>
        <dt>Mandate ID</dt>
        <dd className="ka-mandate__id">{decision.mandate_id ?? "not issued"}</dd>
        <dt>Action</dt>
        <dd>{toolTitle(decision.tool)}</dd>
        <dt>Tier</dt>
        <dd>{decision.effective_tier ?? decision.tier ?? "T3"}, signed by you</dd>
        <dt>Signed</dt>
        <dd>With the key on this device</dd>
      </dl>
      <div className="ka-mandate__foot">
        <span className="kc-caption">The signature and the result are in the audit log.</span>
        <Button variant="ghost" size="sm" iconRight={ArrowRight} onClick={() => openPanel("trust", { tab: "audit" })}>
          View in audit log
        </Button>
      </div>
    </div>
  );
}

function Message({ m }: { m: Msg }) {
  if (m.t === "brief") return <BriefMessage />;
  if (m.t === "owner")
    return (
      <ChatBubble role="owner" meta={m.at}>
        {m.text}
      </ChatBubble>
    );
  if (m.t === "thinking") {
    return (
      <ChatBubble role="copilot">
        <StageLine stage={m.stage} seq={m.seq} />
      </ChatBubble>
    );
  }
  if (m.t === "note") {
    return (
      <div className="ka-note">
        <Repeat size={14} strokeWidth={1.5} aria-hidden />
        {m.text}
        {m.at ? ` · ${m.at}` : ""}
      </div>
    );
  }
  if (m.t === "signed") {
    return (
      <ChatBubble role="copilot" meta={m.at} attachment={<SignedMandate decision={m.decision} />}>
        {m.decision.status === "executed" ? "Signed. It is done, and the record is in the audit log." : "Signed."}
      </ChatBubble>
    );
  }
  const actions = m.actions;
  return (
    <ChatBubble
      role="copilot"
      meta={
        !m.reply.firewall.fallback
          ? m.at
          : m.reply.firewall.rejected?.length
            ? `${m.at} · template answer: the model's draft did not pass the number check`
            : `${m.at} · template answer`
      }
      attachment={
        actions.length ? (
          <div className="ka-attach">
            {actions.map((a, i) => (
              <ActionCard key={a.approval_id ?? `${a.tool}-${i}`} action={a} />
            ))}
          </div>
        ) : undefined
      }
    >
      <RevealSegments segments={m.reply.segments} arrived={m.arrived} />
    </ChatBubble>
  );
}

export function Conversation() {
  const { conversations, active, send } = useAdvisor();
  const conv = conversations.find((c) => c.id === active);
  const scroller = useRef<HTMLDivElement>(null);
  const count = conv?.msgs.length ?? 0;
  const prev = useRef(count);

  useEffect(() => {
    const el = scroller.current;
    if (el && count > prev.current) el.scrollTop = el.scrollHeight;
    prev.current = count;
  }, [count]);

  if (!conv) return <EmptyState onSend={send} />;
  return (
    <>
      <div className="ka-scroll" ref={scroller}>
        <div className="ka-col ka-msgs" role="log" aria-label={`Conversation: ${conv.title}`}>
          {conv.msgs.map((m, i) => (
            <Message key={i} m={m} />
          ))}
        </div>
      </div>
      <div className="ka-dock">
        <div className="ka-col">
          <div className="ka-sugg">
            {SUGGESTIONS.map((s) => (
              <button key={s} type="button" className="ka-chip" onClick={() => send(s)} disabled={conv.busy}>
                {s}
              </button>
            ))}
          </div>
          <Composer onSend={send} disabled={conv.busy} />
          <div className="kc-caption ka-dock__note">{APP_NAME} acts only within the limits you signed.</div>
        </div>
      </div>
    </>
  );
}

/** "Good morning, Maya": time of day from the browser, first name from the brief feed (none until it loads). */
function useGreeting(): string {
  const { id, key } = useBusinessKey("greeting");
  const res = useApi<BriefActivity>(key && `${key}:activity`, () => api.briefActivity(id));
  const hour = new Date().getHours();
  const part = hour < 12 ? "Good morning" : hour < 18 ? "Good afternoon" : "Good evening";
  const name = res.data?.owner_first_name;
  return name ? `${part}, ${name}` : part;
}

function EmptyState({ onSend }: { onSend: (t: string) => void }) {
  const greeting = useGreeting();
  return (
    <div className="ka-empty">
      <div className="ka-col" style={{ display: "flex", flexDirection: "column", gap: 28 }}>
        <div className="ka-greet">
          <Logo variant="mark" />
          <h1>{greeting}</h1>
          <span className="kc-caption">How is the shop today? Ask me anything, or tell me about your products.</span>
        </div>
        <Composer onSend={onSend} autoFocus />
        <div className="ka-sugg">
          {EMPTY_SUGGESTIONS.map((s) => (
            <button key={s} type="button" className="ka-chip" onClick={() => onSend(s)}>
              {s}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
