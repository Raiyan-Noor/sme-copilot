"use client";

import { useBusinessKey } from "@/components/business-context";
import { FactTable, FactValue, Load, PageHeader, Section } from "@/components/data";
import { Badge } from "@/components/ui/badge";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { api } from "@/lib/api";
import { useApi } from "@/lib/use-api";

export default function TodayPage() {
  const { id, key: cashKey } = useBusinessKey("cash");
  const { key: kpiKey } = useBusinessKey("kpis");
  const cash = useApi(cashKey, () => api.cash(id));
  const kpis = useApi(kpiKey, () => api.kpis(id));

  return (
    <>
      <PageHeader title="Today" />
      <Section title="Cash position" description="GET /businesses/{id}/cash">
        <Load state={cash}>
          {(c) => (
            <FactTable
              facts={[
                c.balance,
                c.buffer_days,
                c.runway_days,
                c.runway_date,
                c.runway_stressed_days,
                c.runway_stressed_date,
                c.avg_daily_spend,
                c.last_activity,
                ...c.accounts,
              ]}
            />
          )}
        </Load>
      </Section>
      <Section title="KPIs vs. healthy ranges" description="GET /businesses/{id}/kpis (benchmarks are synthetic)">
        <Load state={kpis}>
          {(k) => (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>KPI</TableHead>
                  <TableHead>Value</TableHead>
                  <TableHead>Healthy range</TableHead>
                  <TableHead>Status</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {k.kpis.map((row) => (
                  <TableRow key={row.kpi_id}>
                    <TableCell>{row.label}</TableCell>
                    <TableCell>
                      <FactValue fact={row.value} />
                    </TableCell>
                    <TableCell>
                      <FactValue fact={row.healthy_min} /> to <FactValue fact={row.healthy_max} />
                    </TableCell>
                    <TableCell>
                      <Badge variant={row.status === "within" ? "secondary" : "outline"}>{row.status}</Badge>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </Load>
      </Section>
    </>
  );
}
