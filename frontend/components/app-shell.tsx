"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";

import { Logo } from "@/components/brand/Logo";
import { BusinessProvider, useBusiness } from "@/components/business-context";
import { errorMessage } from "@/components/data";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { APP_TAGLINE } from "@/config/app";
import { api, ApiError, setPasscode } from "@/lib/api";
import { cn } from "@/lib/utils";
import { useApi } from "@/lib/use-api";

const NAV = [
  { href: "/", label: "Today" },
  { href: "/ask", label: "Ask" },
  { href: "/cash-flow", label: "Cash flow" },
  { href: "/financing", label: "Financing" },
  { href: "/inbox", label: "Inbox" },
  { href: "/trust", label: "Trust" },
];

export function AppShell({ children }: { children: React.ReactNode }) {
  return (
    <BusinessProvider>
      <div className="flex min-h-screen flex-col md:flex-row">
        <Sidebar />
        <div className="flex min-w-0 flex-1 flex-col">
          <TopBar />
          <main className="flex-1 p-4 md:p-8">
            <Gate>{children}</Gate>
          </main>
        </div>
      </div>
    </BusinessProvider>
  );
}

function Sidebar() {
  const pathname = usePathname();
  const { businesses, business, select } = useBusiness();
  return (
    <aside className="flex flex-col gap-4 border-b border-sidebar-border bg-sidebar p-4 md:w-60 md:border-r md:border-b-0">
      <div>
        <Logo className="text-lg" />
        <p className="text-xs text-text-muted">{APP_TAGLINE}</p>
      </div>
      {businesses.data && businesses.data.length > 0 && (
        <label className="flex flex-col gap-1 text-xs text-text-muted">
          Business
          <select
            className="rounded-md border border-input bg-surface px-2 py-1 text-sm text-text"
            value={business?.id ?? ""}
            onChange={(e) => select(e.target.value)}
          >
            {businesses.data.map((b) => (
              <option key={b.id} value={b.id}>
                {b.name}
              </option>
            ))}
          </select>
          {business && <span>Skill Pack: {business.pack_id}</span>}
        </label>
      )}
      <nav className="flex flex-wrap gap-1 md:flex-col">
        {NAV.map((item) => {
          const active = item.href === "/" ? pathname === "/" : pathname.startsWith(item.href);
          return (
            <Link
              key={item.href}
              href={item.href}
              className={cn(
                "rounded-md px-3 py-1.5 text-sm",
                active ? "bg-sidebar-primary text-sidebar-primary-foreground" : "hover:bg-sidebar-accent",
              )}
            >
              {item.label}
            </Link>
          );
        })}
      </nav>
    </aside>
  );
}

function TopBar() {
  const { business, session, resetSession } = useBusiness();
  const clock = useApi(`clock:${session}`, api.clock);
  const [busy, setBusy] = useState(false);

  const advance = async () => {
    setBusy(true);
    try {
      await api.advanceClock({ days: 1 });
    } finally {
      setBusy(false);
      // Every figure depends on the simulated date, so refetch everything.
      resetSession();
    }
  };

  return (
    <header className="flex flex-wrap items-center gap-3 border-b border-border px-4 py-2 text-sm md:px-8">
      {business?.synthetic && <Badge variant="secondary">Synthetic demo data</Badge>}
      {clock.data && (
        <>
          <span className="text-text-muted">
            Simulated date: <span className="text-text tabular-nums">{clock.data.today}</span>
          </span>
          <Button size="sm" variant="outline" onClick={advance} disabled={busy}>
            Fast-forward one day
          </Button>
        </>
      )}
    </header>
  );
}

/** Shows the passcode form when the API rejects the passcode; otherwise the page. */
function Gate({ children }: { children: React.ReactNode }) {
  const { businesses, resetSession } = useBusiness();
  const [value, setValue] = useState("");
  const error = businesses.error;
  const needsPasscode = error instanceof ApiError && error.status === 401;

  if (error !== undefined && !needsPasscode) {
    return <p className="text-sm text-danger">Cannot reach the API: {errorMessage(error)}</p>;
  }
  if (!needsPasscode) return <>{children}</>;
  return (
    <form
      className="flex max-w-sm flex-col gap-3"
      onSubmit={(e) => {
        e.preventDefault();
        setPasscode(value);
        resetSession();
      }}
    >
      <h1 className="text-lg font-semibold">Enter the demo passcode</h1>
      <Input type="password" value={value} onChange={(e) => setValue(e.target.value)} autoFocus />
      <Button type="submit">Continue</Button>
    </form>
  );
}
