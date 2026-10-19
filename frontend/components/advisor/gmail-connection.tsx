"use client";

import { Check, Inbox, LogOut, Mail, RefreshCw, ShieldCheck, X } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

import { AlertBanner } from "@/components/kc/alert-banner";
import { Button } from "@/components/kc/button";
import { StatusPill } from "@/components/kc/status-pill";
import { APP_NAME } from "@/config/app";
import { API_URL, api } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import type { GmailStatus } from "@/lib/types";

const POPUP = "width=520,height=680,menubar=no,toolbar=no";

/**
 * The business's Gmail connection: its status, and connect through Google's consent screen in a popup (so the page
 * underneath, e.g. onboarding, keeps its place). The popup reports back with postMessage; status polling covers a
 * blocked or silently closed popup. The refresh token never reaches the browser: only status comes back.
 */
export function useGmailConnection(id: string) {
  const [status, setStatus] = useState<GmailStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [connecting, setConnecting] = useState(false);
  const watch = useRef<number | null>(null);

  const refresh = useCallback(async () => {
    if (!id) return null;
    try {
      const s = await api.gmailStatus(id);
      setStatus(s);
      return s;
    } catch (e) {
      setError(errorMessage(e));
      return null;
    }
  }, [id]);

  useEffect(() => {
    if (!id) return;
    let live = true;
    api.gmailStatus(id).then(
      (s) => live && setStatus(s),
      (e) => live && setError(errorMessage(e)),
    );
    return () => {
      live = false;
    };
  }, [id]);

  const stopWatching = useCallback(() => {
    if (watch.current !== null) window.clearInterval(watch.current);
    watch.current = null;
    setConnecting(false);
  }, []);

  useEffect(() => {
    const api_origin = new URL(API_URL).origin;
    const onMessage = (e: MessageEvent) => {
      if (e.origin !== api_origin || e.data?.type !== "gmail-connection") return;
      stopWatching();
      if (!e.data.ok) setError("Gmail was not connected. Please try again.");
      void refresh();
    };
    window.addEventListener("message", onMessage);
    return () => {
      window.removeEventListener("message", onMessage);
      if (watch.current !== null) window.clearInterval(watch.current);
    };
  }, [refresh, stopWatching]);

  const connect = useCallback(async () => {
    setError(null);
    // Open the popup inside the click, before any await, so the browser does not block it.
    const popup = window.open("", "gmail-connect", POPUP);
    setConnecting(true);
    try {
      const { authorize_url } = await api.gmailConnect(id);
      if (popup) popup.location.href = authorize_url;
      else window.location.href = authorize_url;
    } catch (e) {
      popup?.close();
      setConnecting(false);
      setError(errorMessage(e));
      return;
    }
    watch.current = window.setInterval(async () => {
      const s = await refresh();
      if (s?.state === "connected" || !popup || popup.closed) stopWatching();
    }, 1500);
  }, [id, refresh, stopWatching]);

  const run = useCallback(
    async (fn: () => Promise<GmailStatus | unknown>) => {
      setError(null);
      try {
        const r = await fn();
        if (r && typeof r === "object" && "state" in r) setStatus(r as GmailStatus);
        else await refresh();
      } catch (e) {
        setError(errorMessage(e));
      }
    },
    [refresh],
  );

  return {
    status,
    setStatus,
    error,
    connecting,
    connect,
    refresh,
    disconnect: () => run(() => api.gmailDisconnect(id)),
    setSource: (source: "gmail" | "sandbox") => run(() => api.gmailSource(id, { source })),
    importRecent: () => run(() => api.gmailImportRecent(id)),
  };
}

export type GmailConnection = ReturnType<typeof useGmailConnection>;

/** What the owner is agreeing to, in plain words, shown before going to Google. */
export function GmailConsent({
  status,
  connecting,
  onContinue,
  onCancel,
}: {
  status: GmailStatus;
  connecting: boolean;
  onContinue: () => void;
  onCancel: () => void;
}) {
  return (
    <div className="ka-gmail__consent">
      <div className="kc-label">Before you go to Google</div>
      <ul className="ka-gmail__list" aria-label={`What ${APP_NAME} will be able to do`}>
        {status.can_do.map((t) => (
          <li key={t}>
            <Check size={16} strokeWidth={1.5} aria-hidden style={{ color: "var(--success)" }} />
            <span>{t}</span>
          </li>
        ))}
      </ul>
      <ul className="ka-gmail__list" aria-label={`What ${APP_NAME} will not do`}>
        {status.cannot_do.map((t) => (
          <li key={t}>
            <X size={16} strokeWidth={1.5} aria-hidden style={{ color: "var(--text-muted)" }} />
            <span>{t}</span>
          </li>
        ))}
      </ul>
      <p className="kc-caption">
        Google will ask you to allow two things: read your email, and send email on your behalf.
        {status.send_allowlist_count === 0
          ? " While this is a demo, nothing is sent for real: approved emails go to the simulated outbox."
          : " While this is a demo, real email only goes to the addresses on the demo allowlist."}
      </p>
      <div className="ka-onb__row">
        <Button iconLeft={Mail} loading={connecting} onClick={onContinue}>
          Continue to Google
        </Button>
        <Button variant="ghost" onClick={onCancel}>
          Cancel
        </Button>
      </div>
    </div>
  );
}

function statePill(s: GmailStatus) {
  if (s.state === "connected" && s.source === "gmail") return <StatusPill size="sm" status="executed" label="Live" />;
  if (s.state === "connected") return <StatusPill size="sm" status="neutral" label="Paused" />;
  if (s.state === "reconnect_needed") return <StatusPill size="sm" status="blocked" label="Reconnect" />;
  if (s.state === "unreachable") return <StatusPill size="sm" status="waiting" label="Retrying" />;
  return <StatusPill size="sm" status="neutral" label="Sandbox" />;
}

/** The Inbox tab's Connections section: where new mail comes from, and the one-click Gmail/sandbox switch. */
export function GmailConnectionCard({ gmail }: { gmail: GmailConnection }) {
  const { status, error, connecting } = gmail;
  const [asking, setAsking] = useState(false);
  if (!status) return null;
  const connected = status.state !== "disconnected" && status.state !== "not_configured";

  return (
    <section className="ka-gmail" aria-label="Connected inbox">
      <div className="ka-gmail__head">
        <Mail size={20} strokeWidth={1.5} aria-hidden style={{ color: "var(--brand-primary)" }} />
        <div style={{ flex: 1, minWidth: 0 }}>
          <div className="kc-label">{status.email_address ?? "Gmail"}</div>
          <div className="kc-caption">{status.message}</div>
        </div>
        {statePill(status)}
      </div>

      {status.state === "reconnect_needed" ? (
        <AlertBanner variant="info" eyebrow="Connection" title="Gmail disconnected — reconnect">
          Google no longer accepts this connection. Your sandbox inbox keeps working until you reconnect.
        </AlertBanner>
      ) : null}
      {error ? (
        <p className="kc-caption" style={{ color: "var(--danger)" }}>
          {error}
        </p>
      ) : null}

      {asking && !connected ? (
        <GmailConsent
          status={status}
          connecting={connecting}
          onContinue={gmail.connect}
          onCancel={() => setAsking(false)}
        />
      ) : (
        <div className="ka-onb__row">
          {status.state === "not_configured" ? (
            <span className="kc-caption">
              To connect Gmail, add {status.missing_settings.join(", ")} to the server&apos;s .env. The sandbox inbox
              works meanwhile.
            </span>
          ) : !connected ? (
            <Button size="sm" variant="secondary" iconLeft={Mail} onClick={() => setAsking(true)}>
              Connect Gmail
            </Button>
          ) : (
            <>
              {status.state === "reconnect_needed" ? (
                <Button size="sm" iconLeft={RefreshCw} loading={connecting} onClick={gmail.connect}>
                  Reconnect
                </Button>
              ) : null}
              {status.source === "gmail" ? (
                <Button size="sm" variant="secondary" iconLeft={Inbox} onClick={() => gmail.setSource("sandbox")}>
                  Use sandbox inbox
                </Button>
              ) : (
                <Button size="sm" variant="secondary" iconLeft={ShieldCheck} onClick={() => gmail.setSource("gmail")}>
                  Use Gmail
                </Button>
              )}
              <Button size="sm" variant="ghost" iconLeft={LogOut} onClick={gmail.disconnect}>
                Disconnect
              </Button>
            </>
          )}
        </div>
      )}
    </section>
  );
}

