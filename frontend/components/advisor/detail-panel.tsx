"use client";

import { ArrowLeft, MessageSquare, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { Button } from "@/components/kc/button";
import { factLabel } from "@/lib/format";
import { cn } from "@/lib/utils";

import { CashPanel } from "./panel-cash";
import { FinancingPanel } from "./panel-financing";
import { EmailPanel, InboxPanel } from "./panel-inbox";
import { OutboxPanel } from "./panel-outbox";
import { PaymentsPanel } from "./panel-payments";
import { TransactionsPanel } from "./panel-transactions";
import { TrustPanel } from "./panel-trust";
import { useAdvisor, type PanelEntry } from "./state";
import { TraceView } from "./trace-view";

/** Header, body and footer of the detail panel (design/app/panels.jsx), filled by each view. */
export function PanelFrame({
  title,
  description,
  footer,
  children,
}: {
  title: React.ReactNode;
  description?: React.ReactNode;
  footer?: React.ReactNode;
  children: React.ReactNode;
}) {
  const { stack, popPanel, closePanel } = useAdvisor();
  const body = useRef<HTMLDivElement>(null);
  const back = stack.length > 1;
  useEffect(() => {
    body.current?.scrollTo(0, 0);
  }, [title]);
  return (
    <>
      <header className={cn("ka-panel__head", back && "has-back")}>
        {back ? (
          <button type="button" className="ka-ibtn" aria-label="Back" onClick={popPanel}>
            <ArrowLeft size={20} strokeWidth={1.5} />
          </button>
        ) : null}
        <div className="ka-panel__titles">
          <h2 className="kc-page-title">{title}</h2>
          {description ? <div className="kc-caption">{description}</div> : null}
        </div>
        <button type="button" className="ka-ibtn" aria-label="Close panel" onClick={closePanel}>
          <X size={20} strokeWidth={1.5} />
        </button>
      </header>
      <div className="ka-panel__body" ref={body}>
        {children}
      </div>
      {footer ? <footer className="ka-panel__foot">{footer}</footer> : null}
    </>
  );
}

function TracePanel({ entry }: { entry: PanelEntry }) {
  const { send, closePanel } = useAdvisor();
  const fact = entry.fact!;
  return (
    <PanelFrame
      title="Where this number comes from"
      footer={
        <Button
          variant="ghost"
          size="sm"
          iconLeft={MessageSquare}
          onClick={() => {
            closePanel();
            send(`Explain ${factLabel(fact.id).toLowerCase()} and how it was worked out.`);
          }}
        >
          Ask about this number
        </Button>
      }
    >
      <TraceView key={fact.id} fact={fact} />
    </PanelFrame>
  );
}

function View({ entry }: { entry: PanelEntry }) {
  switch (entry.view) {
    case "cash":
      return <CashPanel />;
    case "financing":
      return <FinancingPanel />;
    case "inbox":
      return <InboxPanel />;
    case "email":
      return <EmailPanel emailId={entry.emailId!} />;
    case "trust":
      return <TrustPanel tab={entry.tab ?? "limits"} />;
    case "trace":
      return <TracePanel entry={entry} />;
    case "transactions":
      return <TransactionsPanel openId={entry.txId} />;
    case "payments":
      return <PaymentsPanel openId={entry.paymentId} />;
    case "outbox":
      return <OutboxPanel />;
  }
}

const entryKey = (e: PanelEntry) =>
  `${e.view}:${e.tab ?? ""}:${e.emailId ?? ""}:${e.fact?.id ?? ""}:${e.txId ?? ""}:${e.paymentId ?? ""}`;

/** The detail panel: one view at a time, sliding in over the rail; drill-downs stack with a back button. */
export function DetailPanel({ wide }: { wide: boolean }) {
  const { stack } = useAdvisor();
  const top = stack[stack.length - 1];
  // Keep the last view mounted while the panel slides out.
  const [shown, setShown] = useState<PanelEntry | undefined>(top);
  if (top && entryKey(top) !== (shown && entryKey(shown))) setShown(top);
  const open = !!top;
  return (
    <aside
      className={cn("ka-panel", open && "is-open")}
      style={{ "--panel-w": wide ? "760px" : "560px" } as React.CSSProperties}
      aria-hidden={!open}
    >
      {shown ? <View key={entryKey(shown)} entry={shown} /> : null}
    </aside>
  );
}
