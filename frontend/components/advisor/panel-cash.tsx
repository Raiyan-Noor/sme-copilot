"use client";

import { MessageSquare } from "lucide-react";
import { useState } from "react";

import { useBusiness, useBusinessKey } from "@/components/business-context";
import { Button } from "@/components/kc/button";
import { FactNumber, KpiTile } from "@/components/kc/fact";
import { Table, Tabs } from "@/components/kc/misc";
import { Skeleton } from "@/components/ui/skeleton";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import { shortDate } from "@/lib/format";
import type { ComingUpItem, ForecastDay, ForecastResponse } from "@/lib/types";
import { useApi } from "@/lib/use-api";

import { PanelFrame } from "./detail-panel";
import { useAdvisor } from "./state";

const num = (v: unknown) => (typeof v === "number" ? v : 0);

/** Axis ticks for the chart scaffolding (not figures the owner acts on; those are the Facts around it). */
function ticks(min: number, max: number): number[] {
  const span = Math.max(max - min, 1);
  const raw = span / 4;
  const mag = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= raw) ?? raw;
  const out = [];
  for (let v = Math.floor(min / step) * step; v <= max + step / 2; v += step) out.push(v);
  return out;
}

/**
 * Projected balance with its uncertainty band (about 80%), plotted from the forecast's daily Facts. The low point
 * and its label are the engine's min_balance Facts.
 */
function CashChart({
  days,
  low,
  currency,
}: {
  days: ForecastDay[];
  low: { display: string; date: string };
  currency: string;
}) {
  const W = 496,
    H = 210,
    P = { l: 48, r: 8, t: 22, b: 26 };
  const exp = days.map((d) => num(d.expected.value));
  const lo = days.map((d) => num(d.low.value));
  const hi = days.map((d) => num(d.high.value));
  const ys = ticks(Math.min(0, ...lo), Math.max(...hi, 1));
  const yMin = ys[0],
    yMax = ys[ys.length - 1];
  const n = days.length;
  const x = (i: number) => P.l + (i / Math.max(n - 1, 1)) * (W - P.l - P.r);
  const y = (v: number) => P.t + (1 - (v - yMin) / (yMax - yMin || 1)) * (H - P.t - P.b);
  const path = (vals: number[]) =>
    vals.map((v, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(" ");
  const band = `${path(hi)} ${lo.map((v, i) => `L${x(n - 1 - i).toFixed(1)},${y(lo[n - 1 - i]).toFixed(1)}`).join(" ")} Z`;
  const lowIdx = Math.max(
    0,
    days.findIndex((d) => d.date === low.date),
  );
  const t = { fontSize: 11, fill: "var(--text-muted)", fontFamily: "var(--font-body)" };
  const fmt = new Intl.NumberFormat("en-US", {
    style: "currency",
    currency,
    notation: "compact",
    maximumFractionDigits: 1,
  });
  const labels = [0, 0.25, 0.5, 0.75, 1].map((f) => Math.round(f * (n - 1)));
  return (
    <svg
      viewBox={`0 0 ${W} ${H}`}
      width="100%"
      style={{ display: "block" }}
      role="img"
      aria-label="Projected cash balance with likely range"
    >
      {ys.map((v) => (
        <g key={v}>
          <line
            x1={P.l}
            x2={W - P.r}
            y1={y(v)}
            y2={y(v)}
            stroke="var(--border)"
            opacity="0.6"
            strokeDasharray={v === 0 ? "4 5" : undefined}
          />
          <text x={P.l - 8} y={y(v) + 4} textAnchor="end" {...t}>
            {fmt.format(v / 100)}
          </text>
        </g>
      ))}
      <path d={band} fill="var(--chart-1)" opacity="0.08" />
      <path d={path(exp)} fill="none" stroke="var(--chart-1)" strokeWidth="2" strokeLinejoin="round" />
      <circle cx={x(0)} cy={y(exp[0])} r="4" fill="var(--chart-1)" />
      <circle
        cx={x(lowIdx)}
        cy={y(exp[lowIdx])}
        r="4"
        fill="var(--surface-muted)"
        stroke="var(--chart-1)"
        strokeWidth="2"
      />
      <text
        x={x(lowIdx)}
        y={y(exp[lowIdx]) - 10}
        textAnchor={lowIdx < n * 0.15 ? "start" : lowIdx > n * 0.85 ? "end" : "middle"}
        {...t}
        fontWeight="500"
        fill="var(--text)"
      >
        Low {low.display}
      </text>
      {labels.map((i, k) => (
        <text key={k} x={x(i)} y={H - 6} textAnchor={k === 0 ? "start" : k === 4 ? "end" : "middle"} {...t}>
          {shortDate(days[i]?.date)}
        </text>
      ))}
    </svg>
  );
}

type Fix = { key: string; title: string; gain: React.ReactNode; why: React.ReactNode; question: string };

export function CashPanel() {
  const { send, closePanel } = useAdvisor();
  const { business } = useBusiness();
  const { id, key } = useBusinessKey("cash-panel");
  const forecast = useApi<ForecastResponse>(key && `${key}:forecast`, () => api.forecast(id));
  const leaks = useApi(key && `${key}:leaks`, () => api.leaks(id));
  const brief = useApi(key && `${key}:brief`, () => api.brief(id));
  const [days, setDays] = useState<"30" | "60" | "90">("30");
  const ask = (q: string) => {
    closePanel();
    send(q);
  };

  const f = forecast.data;
  const h = f?.horizons.find((x) => String(x.days) === days);
  const fixes: Fix[] = [];
  if (f?.overdue_receivables && num(f.overdue_receivables.value) > 0) {
    fixes.push({
      key: "overdue",
      title: "Collect overdue invoices",
      gain: <FactNumber fact={f.overdue_receivables} tone="positive" />,
      why: f.overdue_receivables_count ? (
        <>
          Customer invoices past due: <FactNumber fact={f.overdue_receivables_count} />. Reminders go out automatically
          only for customers on the limit you signed.
        </>
      ) : (
        "Customer invoices are past due."
      ),
      question: "Who owes me money, and how late are they?",
    });
  }
  for (const l of leaks.data?.slice(0, 3) ?? []) {
    fixes.push({
      key: l.id,
      title: l.about ? `${l.label}: ${l.about}` : l.label,
      gain: (
        <>
          <FactNumber fact={l.yearly_impact} tone="positive" /> a year
        </>
      ),
      why: l.details.slice(0, 2).map((d, i) => (
        <span key={d.fact.id}>
          {i ? " · " : ""}
          {d.label} <FactNumber fact={d.fact} />
        </span>
      )),
      question: `How can I fix this: ${l.label}${l.about ? ` (${l.about})` : ""}?`,
    });
  }

  return (
    <PanelFrame title="Cash flow" description="From your bank feed, scheduled bills and open invoices">
      {forecast.error !== undefined ? (
        <p className="ka-text" style={{ color: "var(--danger)" }}>
          Could not load the forecast: {errorMessage(forecast.error)}
        </p>
      ) : !f || !h ? (
        <Skeleton className="h-80 w-full" />
      ) : (
        <div className="ka-stack" style={{ gap: 40 }}>
          <section className="ka-sec" style={{ gap: 24 }}>
            <Tabs
              size="sm"
              value={days}
              onValueChange={setDays}
              items={[
                { value: "30", label: "Next 30 days" },
                { value: "60", label: "60 days" },
                { value: "90", label: "90 days" },
              ]}
            />
            <p className="ka-advise">
              Here is your cash until <FactNumber fact={h.end_date} />. The line is what I expect; the shaded band is
              the likely range.
            </p>
            <div className="ka-kpis2">
              <KpiTile
                size="md"
                label="Lowest point"
                fact={h.min_balance}
                caption={
                  <>
                    on <FactNumber fact={h.min_balance_date} />
                  </>
                }
              />
              <KpiTile
                size="md"
                label="At the end"
                fact={h.end_balance}
                caption={
                  <>
                    likely <FactNumber fact={h.end_balance_low} /> to <FactNumber fact={h.end_balance_high} />
                  </>
                }
              />
            </div>
            <CashChart
              days={f.daily.slice(0, h.days)}
              low={{ display: h.min_balance.display, date: String(h.min_balance_date.value ?? "") }}
              currency={business?.currency ?? "USD"}
            />
          </section>
          {fixes.length ? (
            <section className="ka-sec">
              <div className="ka-sechead">
                <h3 className="kc-section-title">Ways to raise the low point</h3>
                <span className="kc-caption">Ranked by effect</span>
              </div>
              <ol className="ka-fixes">
                {fixes.map((x, i) => (
                  <li key={x.key}>
                    <span className="n">{i + 1}</span>
                    <span className="t">{x.title}</span>
                    <span className="g">{x.gain}</span>
                    <span className="w">{x.why}</span>
                    <span className="a">
                      <Button
                        variant={i === 0 ? "secondary" : "ghost"}
                        size="sm"
                        iconLeft={MessageSquare}
                        onClick={() => ask(x.question)}
                      >
                        Ask me to prepare it
                      </Button>
                    </span>
                  </li>
                ))}
              </ol>
            </section>
          ) : null}
          {brief.data?.coming_up.length ? (
            <section className="ka-sec">
              <div className="ka-sechead">
                <h3 className="kc-section-title">Coming up</h3>
                <span className="kc-caption">Scheduled</span>
              </div>
              <Table<ComingUpItem>
                density="compact"
                rowKey={(r) => r.id}
                rows={brief.data.coming_up}
                columns={[
                  { key: "date", header: "Date", width: 72, render: (r) => <FactNumber fact={r.due} /> },
                  {
                    key: "what",
                    header: "What",
                    render: (r) => (
                      <div>
                        <div style={{ fontWeight: 500 }}>{r.label}</div>
                        <div className="kc-caption">{r.kind === "receivable" ? "Money in" : "Bill"}</div>
                      </div>
                    ),
                  },
                  {
                    key: "amount",
                    header: "Amount",
                    align: "right",
                    render: (r) => (
                      <FactNumber fact={r.amount} tone={r.kind === "receivable" ? "positive" : "default"} />
                    ),
                  },
                ]}
              />
            </section>
          ) : null}
        </div>
      )}
    </PanelFrame>
  );
}
