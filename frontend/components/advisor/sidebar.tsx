"use client";

import {
  Check,
  ChevronsUpDown,
  CirclePlus,
  Inbox,
  Landmark,
  PanelLeftClose,
  PanelLeftOpen,
  Plus,
  ShieldCheck,
  X,
} from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { Logo } from "@/components/brand/Logo";
import { useBusiness, useBusinessKey } from "@/components/business-context";
import { Button } from "@/components/kc/button";
import { StatusPill } from "@/components/kc/status-pill";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import { useApi } from "@/lib/use-api";
import { cn } from "@/lib/utils";

import { BRIEF_ID, useAdvisor } from "./state";

const initials = (name: string) =>
  name
    .split(/\s+/)
    .filter((w) => /^[A-Za-z]/.test(w))
    .slice(0, 2)
    .map((w) => w[0].toUpperCase())
    .join("");

/** Sidebar (design/app/shell.jsx): conversations, the detail views, and the business and Skill Pack switcher. */
export function Sidebar({
  mini,
  drawer,
  phone,
  onToggle,
  onCloseDrawer,
}: {
  mini: boolean;
  drawer: boolean;
  phone: boolean;
  onToggle: () => void;
  onCloseDrawer: () => void;
}) {
  const { conversations, active, setActive, newConversation, openPanel, toast } = useAdvisor();
  const { businesses, business, select, session, resetSession } = useBusiness();
  const { id, key } = useBusinessKey("inbox");
  const inbox = useApi(key, () => api.inbox(id));
  const packs = useApi(`packs:${session}`, api.packs);
  const [menu, setMenu] = useState(false);
  const router = useRouter();
  const flagged = inbox.data?.held ?? 0;
  const packName = (pid: string) => packs.data?.find((p) => p.id === pid)?.display_name ?? pid;

  const go = (fn: () => void) => () => {
    fn();
    onCloseDrawer();
  };

  const switchPack = async (packId: string) => {
    if (!business || packId === business.pack_id) return;
    setMenu(false);
    try {
      await api.switchPack(business.id, { pack_id: packId });
      toast({ variant: "success", title: `Skill Pack switched to ${packName(packId)}`, description: business.name });
      resetSession();
    } catch (e) {
      toast({ variant: "danger", title: "Could not switch the Skill Pack", description: errorMessage(e) });
    }
  };

  const links = [
    { id: "inbox" as const, label: "Inbox", icon: Inbox, count: flagged },
    { id: "financing" as const, label: "Financing", icon: Landmark, count: 0 },
    { id: "trust" as const, label: "Limits and trust", icon: ShieldCheck, count: 0 },
  ];

  return (
    <nav className={cn("ka-sb", mini && "is-mini", drawer && "is-drawer")} aria-label="Conversations and views">
      <div className="ka-sb__top">
        {mini ? <Logo variant="mark" className="ka-sb__mark" /> : <Logo />}
        {phone ? (
          <button type="button" className="ka-ibtn" aria-label="Close menu" onClick={onCloseDrawer}>
            <X size={20} strokeWidth={1.5} />
          </button>
        ) : (
          <button
            type="button"
            className="ka-ibtn"
            aria-label={mini ? "Expand sidebar" : "Collapse sidebar"}
            title={mini ? "Expand" : "Collapse"}
            onClick={onToggle}
          >
            {mini ? <PanelLeftOpen size={20} strokeWidth={1.5} /> : <PanelLeftClose size={20} strokeWidth={1.5} />}
          </button>
        )}
      </div>
      <div className="ka-sb__new">
        {mini ? (
          <button
            type="button"
            className="ka-ibtn"
            style={{ background: "var(--surface-raised)", color: "var(--text)" }}
            aria-label="New conversation"
            title="New conversation"
            onClick={go(newConversation)}
          >
            <Plus size={20} strokeWidth={1.5} />
          </button>
        ) : (
          <Button variant="secondary" size="md" iconLeft={Plus} fullWidth onClick={go(newConversation)}>
            New conversation
          </Button>
        )}
      </div>
      {mini ? null : (
        <div className="ka-sb__group">
          <div className="ka-sb__label">Conversations</div>
          {conversations.map((c) => (
            <button
              key={c.id}
              type="button"
              className={cn("ka-nav", active === c.id && "is-active")}
              onClick={go(() => setActive(c.id))}
              aria-current={active === c.id ? "page" : undefined}
            >
              <span className="t">{c.id === BRIEF_ID ? "Morning brief" : c.title}</span>
            </button>
          ))}
        </div>
      )}
      <div className="ka-sb__foot">
        {links.map((l) => (
          <button
            key={l.id}
            type="button"
            className="ka-nav"
            title={mini ? l.label : undefined}
            aria-label={mini ? l.label : undefined}
            onClick={go(() => openPanel(l.id))}
          >
            <l.icon size={18} strokeWidth={1.5} aria-hidden />
            {mini ? (
              l.count ? (
                <span className="ka-nav__dot" aria-hidden="true" />
              ) : null
            ) : (
              <span className="t">{l.label}</span>
            )}
            {!mini && l.count ? (
              <span className="ka-nav__count" aria-label={`${l.count} flagged`}>
                {l.count} flagged
              </span>
            ) : null}
          </button>
        ))}
        <div className="ka-sb__sep" />
        {menu && !mini ? (
          <div className="ka-menu" role="menu">
            <div className="ka-sb__label" style={{ padding: "6px 12px 2px" }}>
              Business
            </div>
            {(businesses.data ?? []).map((b) => (
              <button
                key={b.id}
                type="button"
                className="ka-nav"
                role="menuitem"
                onClick={() => {
                  setMenu(false);
                  if (b.id !== business?.id) {
                    select(b.id);
                    toast({ title: `Switched to ${b.name}`, description: `Skill Pack: ${packName(b.pack_id)}` });
                  }
                }}
              >
                <Check
                  size={16}
                  strokeWidth={1.5}
                  style={{ color: "var(--brand-primary)", visibility: b.id === business?.id ? "visible" : "hidden" }}
                  aria-hidden
                />
                <span className="t">{b.name}</span>
              </button>
            ))}
            <button
              type="button"
              className="ka-nav"
              role="menuitem"
              onClick={() => {
                setMenu(false);
                router.push("/start");
              }}
            >
              <CirclePlus size={16} strokeWidth={1.5} style={{ color: "var(--brand-primary)" }} aria-hidden />
              <span className="t">Start fresh: a new business</span>
            </button>
            <div className="ka-sb__label" style={{ padding: "10px 12px 2px" }}>
              Skill Pack
            </div>
            {(packs.data ?? []).map((p) => (
              <button key={p.id} type="button" className="ka-nav" role="menuitem" onClick={() => switchPack(p.id)}>
                <Check
                  size={16}
                  strokeWidth={1.5}
                  style={{
                    color: "var(--brand-primary)",
                    visibility: p.id === business?.pack_id ? "visible" : "hidden",
                  }}
                  aria-hidden
                />
                <span className="t">{p.display_name}</span>
              </button>
            ))}
          </div>
        ) : null}
        <button
          type="button"
          className="ka-shop"
          aria-label="Switch business or Skill Pack"
          aria-expanded={menu}
          onClick={() => (mini ? onToggle() : setMenu((m) => !m))}
        >
          <span className="ka-shop__av">{business ? initials(business.name) : ""}</span>
          {mini ? null : (
            <>
              <span className="ka-shop__txt">
                <div className="ka-shop__name">{business?.name ?? "Loading…"}</div>
                <div className="kc-caption">{business ? `Skill Pack: ${packName(business.pack_id)}` : ""}</div>
              </span>
              <ChevronsUpDown size={16} strokeWidth={1.5} style={{ color: "var(--text-muted)" }} aria-hidden />
            </>
          )}
        </button>
        {mini || !business?.synthetic ? null : (
          <div className="ka-synth">
            <StatusPill status="synthetic" size="sm" />
          </div>
        )}
      </div>
    </nav>
  );
}
