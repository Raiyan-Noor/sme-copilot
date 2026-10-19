"use client";

import { ArrowRight, ChevronDown, Menu, PanelRightOpen, SquarePen } from "lucide-react";
import { usePathname } from "next/navigation";
import { useEffect, useState, useSyncExternalStore } from "react";

import { Logo } from "@/components/brand/Logo";
import { BusinessProvider, useBusiness } from "@/components/business-context";
import { Button } from "@/components/kc/button";
import { TraceScope } from "@/components/kc/fact";
import { Toast } from "@/components/kc/misc";
import { APP_TAGLINE } from "@/config/app";
import { ApiError, setPasscode } from "@/lib/api";
import { errorMessage } from "@/lib/errors";

import { ApprovalSheet } from "./approval-sheet";
import { Conversation } from "./conversation";
import { DemoConsole } from "./demo-console";
import { DetailPanel } from "./detail-panel";
import { Onboarding } from "./onboarding";
import { Rail, TodaySheet } from "./rail";
import { Sidebar } from "./sidebar";
import { AdvisorProvider, BRIEF_ID, NEW_ID, useAdvisor } from "./state";

const DEMO_MODE = process.env.NEXT_PUBLIC_DEMO_MODE === "true";

function useMQ(query: string): boolean {
  return useSyncExternalStore(
    (cb) => {
      const mq = window.matchMedia(query);
      mq.addEventListener("change", cb);
      return () => mq.removeEventListener("change", cb);
    },
    () => window.matchMedia(query).matches,
    () => false,
  );
}

/**
 * The owner app (design/KaChing Advisor.html): sidebar, the conversation centred on the window, the stats rail and
 * the detail panel. Every skeleton route renders this one screen and opens its view (see state.tsx).
 */
function Shell() {
  const a = useAdvisor();
  const phone = useMQ("(max-width:760px)");
  const mid = useMQ("(min-width:761px) and (max-width:1100px)");
  const [userMini, setUserMini] = useState(false);
  const [midOpen, setMidOpen] = useState(false);
  const [railOpen, setRailOpen] = useState(true);
  const [drawer, setDrawer] = useState(false);
  const [today, setToday] = useState(false);

  const panelOpen = a.stack.length > 0;
  const top = a.stack[a.stack.length - 1];
  const wide = top?.view === "email" || top?.view === "transactions";

  useEffect(() => {
    const k = (e: KeyboardEvent) => {
      if (e.key !== "Escape" || a.approval) return;
      if (panelOpen) a.closePanel();
      else {
        setToday(false);
        setDrawer(false);
      }
    };
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  }, [panelOpen, a]);

  const mini = !phone && (mid ? !midOpen : userMini || panelOpen);
  const conv = a.conversations.find((c) => c.id === a.active);
  const title = a.active === NEW_ID ? "" : a.active === BRIEF_ID ? "Morning brief" : (conv?.title ?? "");
  const style = {
    "--sb-w": mini ? "64px" : "248px",
    "--right-w": panelOpen ? (wide ? "760px" : "560px") : railOpen ? "300px" : "0px",
  } as React.CSSProperties;

  return (
    <TraceScope value={a.trace}>
      <div className="ka-app" style={style}>
        <Sidebar
          mini={mini}
          drawer={drawer || (mid && midOpen)}
          phone={phone}
          onToggle={() => (mid ? setMidOpen((x) => !x) : setUserMini((x) => !x))}
          onCloseDrawer={() => {
            setDrawer(false);
            setMidOpen(false);
          }}
        />
        {mid && midOpen ? (
          <div className="ka-scrim" style={{ background: "transparent" }} onClick={() => setMidOpen(false)} />
        ) : null}
        {phone && drawer ? <div className="ka-scrim" onClick={() => setDrawer(false)} /> : null}
        <main className="ka-stage">
          <header className="ka-head">
            <div className="ka-col">
              <span className="ka-head__title">{title}</span>
            </div>
            {!railOpen && !panelOpen ? (
              <div className="ka-head__right">
                <button
                  type="button"
                  className="ka-ibtn"
                  aria-label="Show stats"
                  title="Show stats"
                  onClick={() => setRailOpen(true)}
                >
                  <PanelRightOpen size={20} strokeWidth={1.5} />
                </button>
              </div>
            ) : null}
          </header>
          <header className="ka-phonehead">
            <button type="button" className="ka-ibtn" aria-label="Open menu" onClick={() => setDrawer(true)}>
              <Menu size={20} strokeWidth={1.5} />
            </button>
            <button
              type="button"
              className="ka-today"
              onClick={() => setToday(true)}
              aria-label={`Today, ${a.waiting} waiting for you`}
            >
              Today{a.waiting ? <span className="g">· {a.waiting}</span> : null}
              <ChevronDown size={16} strokeWidth={1.5} style={{ color: "var(--text-muted)" }} aria-hidden />
            </button>
            <button type="button" className="ka-ibtn" aria-label="New conversation" onClick={a.newConversation}>
              <SquarePen size={20} strokeWidth={1.5} />
            </button>
          </header>
          <Conversation key={a.active} />
        </main>
        <Rail hidden={panelOpen || !railOpen || mid} onHide={() => setRailOpen(false)} />
        {phone ? <TodaySheet open={today} onClose={() => setToday(false)} /> : null}
        <DetailPanel wide={wide} />
        <div className="ka-toasts">
          {a.toasts.map((t) => (
            <Toast key={t.id} {...t} onClose={() => a.dismissToast(t.id)} />
          ))}
        </div>
        <ApprovalSheet />
      </div>
    </TraceScope>
  );
}

/** Shows the passcode form when the API rejects the passcode, a plain error if the API is down, else the app. */
function Gate({ children }: { children: React.ReactNode }) {
  const { businesses, resetSession } = useBusiness();
  const [value, setValue] = useState("");
  const error = businesses.error;
  const needsPasscode = error instanceof ApiError && error.status === 401;
  if (error === undefined) return <>{children}</>;
  return (
    <div className="ka-empty" style={{ minHeight: "100vh" }}>
      <div
        className="ka-col"
        style={{
          display: "flex",
          flexDirection: "column",
          gap: 28,
          maxWidth: 420,
        }}
      >
        <div className="ka-greet">
          <Logo variant="mark" />
          <h1>{needsPasscode ? "Enter the demo passcode" : "Cannot reach the server"}</h1>
          <span className="kc-caption">{needsPasscode ? APP_TAGLINE : errorMessage(error)}</span>
        </div>
        {needsPasscode ? (
          <form
            className="ka-compose"
            onSubmit={(e) => {
              e.preventDefault();
              setPasscode(value);
              resetSession();
            }}
          >
            <input
              type="password"
              value={value}
              onChange={(e) => setValue(e.target.value)}
              aria-label="Passcode"
              autoFocus
            />
            <Button type="submit" size="sm" iconLeft={ArrowRight} aria-label="Continue" disabled={!value} />
          </form>
        ) : (
          <Button variant="secondary" onClick={resetSession}>
            Try again
          </Button>
        )}
      </div>
    </div>
  );
}

function PerBusiness() {
  const { business } = useBusiness();
  const pathname = usePathname();
  // Start fresh: a new business is set up full-screen, outside any existing business's view.
  if (pathname === "/start") return <Onboarding />;
  // Demo console (a recording tool): only when the build has NEXT_PUBLIC_DEMO_MODE on; otherwise the route is a 404.
  if (pathname === "/demo-console" && DEMO_MODE) return <DemoConsole />;
  // A business switch starts a fresh day view: its own brief, conversations and approvals.
  return (
    <AdvisorProvider key={business?.id ?? "none"}>
      <Shell />
    </AdvisorProvider>
  );
}

export function AdvisorApp() {
  return (
    <BusinessProvider>
      <Gate>
        <PerBusiness />
      </Gate>
    </BusinessProvider>
  );
}
