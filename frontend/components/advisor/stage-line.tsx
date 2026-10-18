"use client";

import { useEffect, useState } from "react";

import { Segments } from "@/components/kc/fact";
import type { ReplySegment, StageEvent } from "@/lib/types";

/** What the agent is doing, from the stage events the planner loop emits as each step starts. */
const STAGE_LINES: Record<StageEvent["stage"], string> = {
  received: "Reading your question…",
  thinking: "Thinking…",
  tool: "Looking that up…",
  action: "Preparing an action for your approval…",
  firewall: "Double-checking every number…",
  fixing: "Fixing a number…",
};

/** One line per read tool. A tool missing here gets the generic "tool" line. */
const TOOL_LINES: Record<string, string> = {
  get_cash_position: "Checking your cash position…",
  get_forecast: "Looking ahead at your cash…",
  get_runway: "Working out how long your cash lasts…",
  get_profit_and_loss: "Looking at your sales…",
  get_margins: "Checking your products…",
  get_kpis: "Comparing your numbers with healthy ranges…",
  list_receivables: "Checking who owes you money…",
  list_upcoming_bills: "Checking your upcoming bills…",
  list_leaks: "Looking for money going to waste…",
  list_inbox: "Going through your inbox…",
  explain_fact: "Tracing a number to its source…",
  match_financing: "Matching financing options…",
  get_passport: "Preparing your business passport…",
  get_loan_application_draft: "Drafting your loan application…",
  get_ad_campaigns: "Reviewing your ad campaigns…",
  list_products: "Checking your products…",
};

/** Shown in turn when no event has arrived for a while, so the screen never looks stuck. */
const IDLE_LINES = ["Reasoning…", "Weighing the options…", "Almost there…"];
const IDLE_AFTER_MS = 3000;

export type Stage = Pick<StageEvent, "stage" | "tool">;

export function stageLine(stage: Stage | undefined, fallback = STAGE_LINES.received): string {
  if (!stage) return fallback;
  if (stage.stage === "tool" && stage.tool) return TOOL_LINES[stage.tool] ?? STAGE_LINES.tool;
  return STAGE_LINES[stage.stage];
}

/**
 * The waiting line in a copilot bubble: the latest stage, or (after three quiet seconds) the idle lines in turn.
 * `seq` changes with every stage event, so a repeated stage (thinking → thinking) still restarts the idle timer.
 */
export function StageLine({ stage, seq = 0, initial }: { stage?: Stage; seq?: number; initial?: string }) {
  const [idle, setIdle] = useState(-1);
  useEffect(() => {
    setIdle(-1);
    let n = -1;
    let timer = window.setTimeout(function tick() {
      n += 1;
      setIdle(n);
      timer = window.setTimeout(tick, IDLE_AFTER_MS);
    }, IDLE_AFTER_MS);
    return () => window.clearTimeout(timer);
  }, [seq, stage?.stage, stage?.tool]);
  const line = idle >= 0 ? IDLE_LINES[idle % IDLE_LINES.length] : stageLine(stage, initial);
  return (
    <span className="kc-caption" role="status" aria-live="polite">
      {line}
    </span>
  );
}

const REVEAL_MS = 700;
const FRAME_MS = 16;

/**
 * A reply that has already passed the Numeric Firewall, revealed over a moment instead of appearing at once.
 * Only checked text is ever shown (the reply arrives whole); facts appear whole, never digit by digit.
 */
export function RevealSegments({ segments, arrived }: { segments: ReplySegment[]; arrived: number }) {
  const total = segments.reduce((n, s) => n + s.text.length, 0);
  // Animate only a reply that just arrived, not one re-mounted when the owner switches conversations.
  const [shown, setShown] = useState(() => {
    const reduced = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    return Date.now() - arrived < 1000 && !reduced ? 0 : total;
  });
  useEffect(() => {
    if (shown >= total) return;
    const step = Math.max(1, Math.ceil(total / (REVEAL_MS / FRAME_MS)));
    const t = window.setTimeout(() => setShown((n) => Math.min(total, n + step)), FRAME_MS);
    return () => window.clearTimeout(t);
  }, [shown, total]);
  if (shown >= total) return <Segments segments={segments} />;
  const visible: ReplySegment[] = [];
  let at = 0;
  for (const s of segments) {
    if (at >= shown) break;
    visible.push(s.fact_id ? s : { ...s, text: s.text.slice(0, shown - at) });
    at += s.text.length;
  }
  return <Segments segments={visible} />;
}
