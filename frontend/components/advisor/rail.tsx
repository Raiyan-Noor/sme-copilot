"use client";

import { ArrowUpRight, CircleAlert, CircleCheck, Clock, FastForward, PanelRightClose, X } from "lucide-react";

import { useBusiness, useBusinessKey } from "@/components/business-context";
import { Button } from "@/components/kc/button";
import { FactNumber, KpiTile } from "@/components/kc/fact";
import { api } from "@/lib/api";
import { shortDate } from "@/lib/format";
import type { ForecastResponse } from "@/lib/types";
import { useApi } from "@/lib/use-api";
import { cn } from "@/lib/utils";

import { useFastForward } from "./fast-forward";
import { useAdvisor } from "./state";

const num = (v: unknown) => (typeof v === "number" ? v : 0);

/** The 30-day expected balance as a sparkline. Plotted from Fact values; the labels around it are Facts. */
function Sparkline({ forecast, w = 252, h = 64 }: { forecast: ForecastResponse; w?: number; h?: number }) {
  const days = forecast.daily.slice(0, 30).map((d) => num(d.expected.value));
  if (days.length < 2) return null;
  const max = Math.max(...days, 1);
  const min = Math.min(...days, 0);
  const x = (i: number) => (i / (days.length - 1)) * w;
  const y = (v: number) => 4 + (1 - (v - min) / (max - min || 1)) * (h - 8);
  const line = days.map((v, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(" ");
  const low = days.reduce((m, v, i) => (v < days[m] ? i : m), 0);
  return (
    <svg
      viewBox={`0 0 ${w} ${h}`}
      width="100%"
      height={h}
      style={{ display: "block", overflow: "visible" }}
      role="img"
      aria-label="Expected cash, next 30 days"
    >
      {min < 0 ? (
        <line x1="0" x2={w} y1={y(0)} y2={y(0)} stroke="var(--chart-3)" strokeDasharray="4 5" strokeWidth="1.25" />
      ) : null}
      <path d={`${line} L${w},${h} L0,${h} Z`} fill="var(--chart-1)" opacity="0.06" />
      <path d={line} fill="none" stroke="var(--chart-1)" strokeWidth="1.5" strokeLinejoin="round" />
      <circle cx={x(0)} cy={y(days[0])} r="3" fill="var(--chart-1)" />
      <circle cx={x(low)} cy={y(days[low])} r="3" fill="var(--surface)" stroke="var(--chart-1)" strokeWidth="1.5" />
    </svg>
  );
}

export function RailBody() {
  const { openPanel, waiting, goToWaiting, ledgerVersion } = useAdvisor();
  const { session } = useBusiness();
  const { id, key } = useBusinessKey("rail");
  const cash = useApi(key && `${key}:cash:${ledgerVersion}`, () => api.cash(id));
  const forecast = useApi(key && `${key}:forecast:${ledgerVersion}`, () => api.forecast(id));
  const verify = useApi(`verify:${session}`, api.auditVerify);
  const ff = useFastForward();
  const h30 = forecast.data?.horizons.find((h) => h.days === 30);

  return (
    <>
      <div className="ka-rail__stats">
        <KpiTile size="md" label="Cash on hand" fact={cash.data?.balance} caption="across your accounts" />
        <KpiTile
          size="md"
          label="Runway"
          fact={cash.data?.runway_days}
          caption={
            cash.data?.runway_date.value ? (
              <>
                if no money came in, until <FactNumber fact={cash.data.runway_date} />
              </>
            ) : (
              "if no money came in"
            )
          }
        />
        <KpiTile
          size="md"
          label="Lowest point, next 30 days"
          fact={h30?.min_balance}
          caption={
            h30 ? (
              <>
                on <FactNumber fact={h30.min_balance_date} />
              </>
            ) : undefined
          }
        />
      </div>
      <div className="ka-rail__sec">
        <button type="button" className="ka-spark" onClick={() => openPanel("cash")} aria-label="Open cash flow">
          <div className="ka-spark__row">
            <span className="kc-label" style={{ color: "var(--text-muted)", fontWeight: 400 }}>
              Cash, next 30 days
            </span>
            <ArrowUpRight size={16} strokeWidth={1.5} style={{ color: "var(--text-muted)" }} aria-hidden />
          </div>
          {forecast.data ? <Sparkline forecast={forecast.data} /> : <div style={{ height: 64 }} />}
          <div className="ka-spark__row">
            <span className="kc-caption">{h30 ? `Ends near ${h30.end_balance.display}` : ""}</span>
            <span className="kc-caption">{h30 ? h30.end_date.display : ""}</span>
          </div>
        </button>
      </div>
      <div className="ka-rail__sec">
        <button type="button" className={cn("ka-waiting", !waiting && "is-zero")} onClick={goToWaiting}>
          {waiting ? (
            <Clock size={18} strokeWidth={1.5} aria-hidden />
          ) : (
            <CircleCheck size={18} strokeWidth={1.5} aria-hidden />
          )}
          <span>{waiting ? "Waiting for you" : "Nothing waiting"}</span>
          <span className="n">{waiting}</span>
        </button>
      </div>
      <div className="ka-rail__foot" style={{ display: "flex", flexDirection: "column", gap: 16 }}>
        <Button variant="secondary" size="sm" iconLeft={FastForward} loading={ff.busy} onClick={ff.run} fullWidth>
          Fast-forward to tomorrow 7:00
        </Button>
        <button type="button" className="ka-anchor" onClick={() => openPanel("trust", { tab: "audit" })}>
          {verify.data && !verify.data.ok ? (
            <span style={{ color: "var(--danger)", display: "flex" }}>
              <CircleAlert size={14} strokeWidth={1.5} aria-hidden />
            </span>
          ) : (
            <span className="ok">
              <CircleCheck size={14} strokeWidth={1.5} aria-hidden />
            </span>
          )}
          <span>
            {!verify.data ? "Checking the audit log…" : verify.data.ok ? "Audit log verified" : "Audit log broken"}
          </span>
          <span style={{ marginLeft: "auto" }}>{verify.data ? `${verify.data.entries} records` : ""}</span>
        </button>
      </div>
    </>
  );
}

function useToday(): string {
  const { session } = useBusiness();
  const clock = useApi(`clock:${session}`, api.clock);
  return clock.data ? shortDate(clock.data.today) : "";
}

export function Rail({ hidden, onHide }: { hidden: boolean; onHide: () => void }) {
  const today = useToday();
  return (
    <aside className={cn("ka-rail", hidden && "is-hidden")} aria-label="Today at a glance" aria-hidden={hidden}>
      <div className="ka-rail__head">
        <span className="kc-label" style={{ color: "var(--text-muted)", fontWeight: 400 }}>
          Today, {today}
        </span>
        <button
          type="button"
          className="ka-ibtn"
          aria-label="Hide stats"
          title="Hide stats"
          onClick={onHide}
          style={{ marginRight: -8 }}
        >
          <PanelRightClose size={20} strokeWidth={1.5} />
        </button>
      </div>
      <RailBody />
    </aside>
  );
}

/** Phone: the rail opens as a full-screen "Today" sheet. */
export function TodaySheet({ open, onClose }: { open: boolean; onClose: () => void }) {
  const today = useToday();
  const { business } = useBusiness();
  return (
    <div className={cn("ka-todaysheet", open && "is-open")} role="dialog" aria-label="Today" aria-hidden={!open}>
      <div className="ka-panel__head">
        <div className="ka-panel__titles">
          <h2 className="kc-page-title">Today</h2>
          <div className="kc-caption">
            {today} · {business?.name}
          </div>
        </div>
        <button type="button" className="ka-ibtn" aria-label="Close" onClick={onClose}>
          <X size={20} strokeWidth={1.5} />
        </button>
      </div>
      <div className="ka-rail">
        <RailBody />
      </div>
    </div>
  );
}
