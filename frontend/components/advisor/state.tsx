"use client";

import { usePathname, useRouter } from "next/navigation";
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";

import { useBusiness } from "@/components/business-context";
import type { FactRef } from "@/components/kc/fact";
import type { ToastData } from "@/components/kc/misc";
import { chatStream } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import { nowTime } from "@/lib/format";
import type { ActionEvent, Decision, ReplyEvent, StageEvent } from "@/lib/types";

import type { Stage } from "./stage-line";

export type PanelView = "cash" | "financing" | "inbox" | "trust" | "email" | "trace" | "transactions";
export type TrustTab = "limits" | "audit" | "anchors" | "redteam";
export type PanelEntry = { view: PanelView; tab?: TrustTab; emailId?: string; fact?: FactRef; txId?: string };

/** The routes from the skeleton, each opening the matching view of the one conversation-first screen. */
const ROUTE_PANEL: Record<string, PanelView> = {
  "/cash-flow": "cash",
  "/transactions": "transactions",
  "/financing": "financing",
  "/inbox": "inbox",
  "/trust": "trust",
};
const PANEL_ROUTE: Partial<Record<PanelView, string>> = {
  cash: "/cash-flow",
  transactions: "/transactions",
  financing: "/financing",
  inbox: "/inbox",
  trust: "/trust",
};

const NO_ENTRIES: PanelEntry[] = [];

export type Msg =
  | { t: "brief" }
  | { t: "owner"; text: string; at: string }
  | { t: "thinking"; tools: string[]; stage?: Stage; seq: number }
  | { t: "reply"; reply: ReplyEvent; actions: ActionEvent[]; at: string; arrived: number }
  | { t: "note"; text: string; at?: string }
  | { t: "signed"; decision: Decision; at: string };

export type Conversation = { id: string; title: string; msgs: Msg[]; serverId?: string; busy: boolean };

export type ApprovalOpen = { approvalId: string; context?: React.ReactNode };
export type Resolution = "executed" | "denied" | "declined";

type Toast = ToastData & { id: number };

type AdvisorValue = {
  // Panels
  stack: PanelEntry[];
  openPanel: (view: PanelView, opts?: Omit<PanelEntry, "view">) => void;
  pushPanel: (entry: PanelEntry) => void;
  popPanel: () => void;
  closePanel: () => void;
  setPanelTab: (tab: TrustTab) => void;
  trace: (fact: FactRef) => void;
  // Toasts
  toasts: Toast[];
  toast: (t: ToastData) => void;
  dismissToast: (id: number) => void;
  // Approvals: the gateway's pending approvals the owner has seen, and how each was resolved here
  approval: ApprovalOpen | null;
  openApproval: (a: ApprovalOpen) => void;
  closeApproval: () => void;
  resolved: Record<string, Resolution>;
  resolve: (approvalId: string, how: Resolution, decision?: Decision) => void;
  addPending: (ids: string[]) => void;
  waiting: number;
  // Conversations
  conversations: Conversation[];
  active: string;
  setActive: (id: string) => void;
  newConversation: () => void;
  send: (text: string) => void;
  /** Scroll target on the brief: "waiting" scrolls to the first thing that needs the owner. */
  scrollRequest: number;
  goToWaiting: () => void;
};

const AdvisorContext = createContext<AdvisorValue | null>(null);

export const BRIEF_ID = "brief";
export const NEW_ID = "new";

export function AdvisorProvider({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const { business } = useBusiness();
  const businessId = business?.id ?? "";

  // ---- Panels, synced with the route so every skeleton route deep-links to its view.
  const routePanel = ROUTE_PANEL[pathname];
  const [extra, setExtra] = useState<{ route: string; entries: PanelEntry[]; tab?: TrustTab }>({
    route: pathname,
    entries: [],
  });
  const current = useMemo(
    () => (extra.route === pathname ? extra : { route: pathname, entries: NO_ENTRIES, tab: undefined }),
    [extra, pathname],
  );
  const stack = useMemo<PanelEntry[]>(
    () => [...(routePanel ? [{ view: routePanel, tab: current.tab }] : []), ...current.entries],
    [routePanel, current.tab, current.entries],
  );

  const openPanel = useCallback(
    (view: PanelView, opts: Omit<PanelEntry, "view"> = {}) => {
      const route = PANEL_ROUTE[view];
      if (route) {
        setExtra({ route, entries: [], tab: opts.tab });
        if (route !== pathname) router.push(route);
      } else {
        setExtra({ route: pathname, entries: [{ view, ...opts }], tab: current.tab });
      }
    },
    [pathname, router, current.tab],
  );
  const pushPanel = useCallback(
    (entry: PanelEntry) => setExtra({ route: pathname, entries: [...current.entries, entry], tab: current.tab }),
    [pathname, current.entries, current.tab],
  );
  const popPanel = useCallback(() => {
    if (current.entries.length) setExtra({ ...current, route: pathname, entries: current.entries.slice(0, -1) });
    else if (routePanel) router.push("/");
  }, [current, pathname, routePanel, router]);
  const closePanel = useCallback(() => {
    setExtra({ route: routePanel ? "/" : pathname, entries: [] });
    if (routePanel) router.push("/");
  }, [pathname, routePanel, router]);
  const setPanelTab = useCallback(
    (tab: TrustTab) => setExtra({ route: pathname, entries: current.entries, tab }),
    [pathname, current.entries],
  );
  const trace = useCallback((fact: FactRef) => pushPanel({ view: "trace", fact }), [pushPanel]);

  // ---- Toasts
  const [toasts, setToasts] = useState<Toast[]>([]);
  const nextToast = useRef(0);
  const dismissToast = useCallback((id: number) => setToasts((x) => x.filter((t) => t.id !== id)), []);
  const toast = useCallback(
    (t: ToastData) => {
      const id = ++nextToast.current;
      setToasts((x) => [...x, { ...t, id }]);
      setTimeout(() => dismissToast(id), 4500);
    },
    [dismissToast],
  );

  // ---- Conversations
  const [conversations, setConversations] = useState<Conversation[]>([
    { id: BRIEF_ID, title: "Morning brief", msgs: [{ t: "brief" }], busy: false },
  ]);
  const [active, setActiveState] = useState<string>(BRIEF_ID);
  const [scrollRequest, setScrollRequest] = useState(0);

  // ---- Approvals
  const [approval, setApproval] = useState<ApprovalOpen | null>(null);
  const [resolved, setResolved] = useState<Record<string, Resolution>>({});
  const [pending, setPending] = useState<string[]>([]);
  const addPending = useCallback(
    (ids: string[]) => setPending((p) => (ids.every((i) => p.includes(i)) ? p : [...new Set([...p, ...ids])])),
    [],
  );
  const waiting = pending.filter((id) => !resolved[id]).length;

  const update = useCallback((id: string, fn: (c: Conversation) => Conversation) => {
    setConversations((cs) => cs.map((c) => (c.id === id ? fn(c) : c)));
  }, []);

  const resolve = useCallback(
    (approvalId: string, how: Resolution, decision?: Decision) => {
      setResolved((r) => ({ ...r, [approvalId]: how }));
      if (how === "executed" && decision) {
        const target = active === NEW_ID ? BRIEF_ID : active;
        update(target, (c) => ({ ...c, msgs: [...c.msgs, { t: "signed", decision, at: nowTime() }] }));
      }
    },
    [active, update],
  );

  // A pathname of /ask opens a fresh conversation, as the skeleton's Ask route did.
  const [askRoute, setAskRoute] = useState<string | null>(null);
  if (pathname === "/ask" && askRoute !== pathname) {
    setAskRoute(pathname);
    setActiveState(NEW_ID);
  } else if (pathname !== "/ask" && askRoute !== null) {
    setAskRoute(null);
  }

  const setActive = useCallback((id: string) => setActiveState(id), []);
  const newConversation = useCallback(() => setActiveState(NEW_ID), []);
  const goToWaiting = useCallback(() => {
    setActiveState(BRIEF_ID);
    setScrollRequest((n) => n + 1);
  }, []);

  const conversationsRef = useRef(conversations);
  useEffect(() => {
    conversationsRef.current = conversations;
  }, [conversations]);

  const send = useCallback(
    (text: string) => {
      if (!businessId) return;
      let id = active;
      if (id === NEW_ID) {
        id = `c${Date.now()}`;
        setConversations((cs) => [...cs, { id, title: text, msgs: [], busy: false }]);
        setActiveState(id);
      }
      const convId = id;
      const serverId = conversationsRef.current.find((c) => c.id === convId)?.serverId;
      update(convId, (c) => ({
        ...c,
        busy: true,
        msgs: [...c.msgs, { t: "owner", text, at: nowTime() }, { t: "thinking", tools: [], seq: 0 }],
      }));

      const replaceThinking = (m: Msg | null) =>
        update(convId, (c) => {
          const i = c.msgs.findLastIndex((x) => x.t === "thinking");
          if (i < 0) return m ? { ...c, msgs: [...c.msgs, m] } : c;
          const msgs = [...c.msgs];
          if (m) msgs[i] = m;
          else msgs.splice(i, 1);
          return { ...c, msgs };
        });

      void (async () => {
        const actions: ActionEvent[] = [];
        try {
          for await (const { event, data } of chatStream(businessId, { message: text, conversation_id: serverId })) {
            if (event === "conversation") {
              const sid = (data as { conversation_id: string }).conversation_id;
              update(convId, (c) => ({ ...c, serverId: sid }));
            } else if (event === "stage") {
              const { stage, tool } = data as StageEvent;
              update(convId, (c) => ({
                ...c,
                msgs: c.msgs.map((m) => (m.t === "thinking" ? { ...m, stage: { stage, tool }, seq: m.seq + 1 } : m)),
              }));
            } else if (event === "tool_call") {
              const tool = (data as { tool: string }).tool;
              update(convId, (c) => ({
                ...c,
                msgs: c.msgs.map((m) => (m.t === "thinking" ? { ...m, tools: [...m.tools, tool] } : m)),
              }));
            } else if (event === "action") {
              const a = data as ActionEvent;
              actions.push(a);
              if (a.status === "pending_approval" && a.approval_id) addPending([a.approval_id]);
            } else if (event === "reply") {
              replaceThinking({ t: "reply", reply: data as ReplyEvent, actions: [...actions], at: nowTime(), arrived: Date.now() });
            } else if (event === "error") {
              // Shown above the pending reply: the turn may still finish with template text.
              const note: Msg = { t: "note", text: (data as { message: string }).message, at: nowTime() };
              update(convId, (c) => {
                const i = c.msgs.findLastIndex((m) => m.t === "thinking");
                const msgs = [...c.msgs];
                msgs.splice(i < 0 ? msgs.length : i, 0, note);
                return { ...c, msgs };
              });
            }
          }
          replaceThinking(null);
        } catch (e) {
          replaceThinking({ t: "note", text: `I could not reach the assistant: ${errorMessage(e)}`, at: nowTime() });
        } finally {
          update(convId, (c) => ({ ...c, busy: false }));
        }
      })();
    },
    [active, businessId, update, addPending],
  );

  const value: AdvisorValue = {
    stack,
    openPanel,
    pushPanel,
    popPanel,
    closePanel,
    setPanelTab,
    trace,
    toasts,
    toast,
    dismissToast,
    approval,
    openApproval: setApproval,
    closeApproval: () => setApproval(null),
    resolved,
    resolve,
    addPending,
    waiting,
    conversations,
    active,
    setActive,
    newConversation,
    send,
    scrollRequest,
    goToWaiting,
  };
  return <AdvisorContext.Provider value={value}>{children}</AdvisorContext.Provider>;
}

export function useAdvisor(): AdvisorValue {
  const ctx = useContext(AdvisorContext);
  if (!ctx) throw new Error("useAdvisor must be used inside <AdvisorProvider>");
  return ctx;
}
