"use client";

import { useState } from "react";

import { useBusinessKey } from "@/components/business-context";
import { FactValue, Load, PageHeader, Section } from "@/components/data";
import { Button } from "@/components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { api } from "@/lib/api";
import { useApi } from "@/lib/use-api";

export default function CashFlowPage() {
  const [period, setPeriod] = useState<"month" | "week">("month");
  const { id, key: forecastKey } = useBusinessKey("forecast");
  const { key: pnlKey } = useBusinessKey("pnl");
  const { key: txKey } = useBusinessKey("transactions");
  const forecast = useApi(forecastKey, () => api.forecast(id));
  const pnl = useApi(pnlKey && `${pnlKey}:${period}`, () => api.pnl(id, period));
  const transactions = useApi(txKey, () => api.transactions(id, { limit: 50 }));

  return (
    <>
      <PageHeader title="Cash flow" />
      <Section title="Forecast horizons" description="GET /businesses/{id}/forecast">
        <Load state={forecast}>
          {(f) => (
            <>
              <p className="mb-2 text-sm text-text-muted">
                As of {f.as_of} · start balance <FactValue fact={f.start_balance} /> · overdue receivables{" "}
                <FactValue fact={f.overdue_receivables} />
              </p>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Horizon</TableHead>
                    <TableHead>End date</TableHead>
                    <TableHead>End balance</TableHead>
                    <TableHead>Low</TableHead>
                    <TableHead>High</TableHead>
                    <TableHead>Inflows</TableHead>
                    <TableHead>Outflows</TableHead>
                    <TableHead>Lowest balance</TableHead>
                    <TableHead>Lowest on</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {f.horizons.map((h) => (
                    <TableRow key={h.days}>
                      <TableCell className="tabular-nums">{h.days} days</TableCell>
                      <TableCell><FactValue fact={h.end_date} /></TableCell>
                      <TableCell><FactValue fact={h.end_balance} /></TableCell>
                      <TableCell><FactValue fact={h.end_balance_low} /></TableCell>
                      <TableCell><FactValue fact={h.end_balance_high} /></TableCell>
                      <TableCell><FactValue fact={h.inflows} /></TableCell>
                      <TableCell><FactValue fact={h.outflows} /></TableCell>
                      <TableCell><FactValue fact={h.min_balance} /></TableCell>
                      <TableCell><FactValue fact={h.min_balance_date} /></TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
              <details className="mt-4 text-sm">
                <summary className="cursor-pointer">Daily path ({f.daily.length} days)</summary>
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Date</TableHead>
                      <TableHead>Expected</TableHead>
                      <TableHead>Low</TableHead>
                      <TableHead>High</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {f.daily.map((d) => (
                      <TableRow key={d.date}>
                        <TableCell className="tabular-nums">{d.date}</TableCell>
                        <TableCell><FactValue fact={d.expected} /></TableCell>
                        <TableCell><FactValue fact={d.low} /></TableCell>
                        <TableCell><FactValue fact={d.high} /></TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </details>
            </>
          )}
        </Load>
      </Section>
      <Section title="Profit and loss" description="GET /businesses/{id}/pnl">
        <div className="mb-4 flex gap-2">
          {(["month", "week"] as const).map((p) => (
            <Button key={p} size="sm" variant={p === period ? "default" : "outline"} onClick={() => setPeriod(p)}>
              By {p}
            </Button>
          ))}
        </div>
        <Load state={pnl}>
          {(r) => {
            const lineIds = Array.from(new Set(r.periods.flatMap((p) => Object.keys(p.lines))));
            return (
              <div className="overflow-x-auto">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Line</TableHead>
                      {r.periods.map((p) => (
                        <TableHead key={p.period}>{p.period}</TableHead>
                      ))}
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {lineIds.map((line) => (
                      <TableRow key={line}>
                        <TableCell className="font-mono text-xs">{line}</TableCell>
                        {r.periods.map((p) => (
                          <TableCell key={p.period}>
                            <FactValue fact={p.lines[line]} />
                          </TableCell>
                        ))}
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            );
          }}
        </Load>
      </Section>
      <Section title="Recent transactions" description="GET /businesses/{id}/transactions">
        <Load state={transactions}>
          {(page) => (
            <>
              <p className="mb-2 text-sm text-text-muted">
                Showing {page.items.length} of {page.total}
              </p>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Date</TableHead>
                    <TableHead>Description</TableHead>
                    <TableHead>Category</TableHead>
                    <TableHead>Amount (minor units)</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {page.items.map((t) => (
                    <TableRow key={t.id}>
                      <TableCell className="tabular-nums">{t.posted_on}</TableCell>
                      <TableCell>{t.description}</TableCell>
                      <TableCell>{t.category}</TableCell>
                      <TableCell className="tabular-nums">
                        {t.amount_minor} {t.currency}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </>
          )}
        </Load>
      </Section>
    </>
  );
}
