"use client";

import { useState } from "react";

import { useBusinessKey } from "@/components/business-context";
import { FactTable, Load, NotYetAvailable, PageHeader, Section } from "@/components/data";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { api } from "@/lib/api";
import { useApi } from "@/lib/use-api";

export default function AskPage() {
  const [prefix, setPrefix] = useState("");
  const [factId, setFactId] = useState("");
  const { id, key } = useBusinessKey("facts");
  const facts = useApi(key && `${key}:${prefix}`, () => api.facts(id, { prefix, limit: 200 }));
  const trace = useApi(key && factId ? `${key}:explain:${factId}` : null, () => api.explainFact(id, factId, 20));

  return (
    <>
      <PageHeader title="Ask" />
      <Section title="Chat">
        <NotYetAvailable what="The planner chat (SSE)" prompt="11" />
      </Section>
      <Section title="Where a number comes from" description="GET /businesses/{id}/facts/{fact_id}/explain">
        {factId ? (
          <Load state={trace}>
            {(t) => (
              <div className="flex flex-col gap-4">
                <FactTable facts={t.facts} />
                <p className="text-sm text-text-muted">
                  Source rows: showing {t.rows.length} of {t.rows_total}
                </p>
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Row</TableHead>
                      <TableHead>Kind</TableHead>
                      <TableHead>Date</TableHead>
                      <TableHead>Amount (minor units)</TableHead>
                      <TableHead>Category</TableHead>
                      <TableHead>Text</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {t.rows.map((r) => (
                      <TableRow key={r.id}>
                        <TableCell className="font-mono text-xs">{r.id}</TableCell>
                        <TableCell>{r.kind}</TableCell>
                        <TableCell className="tabular-nums">{r.date}</TableCell>
                        <TableCell className="tabular-nums">{r.amount_minor}</TableCell>
                        <TableCell>{r.category}</TableCell>
                        <TableCell>{r.text}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            )}
          </Load>
        ) : (
          <p className="text-sm text-text-muted">Pick a fact below to see its inputs and source rows.</p>
        )}
      </Section>
      <Section title="All facts" description="GET /businesses/{id}/facts">
        <Input
          className="mb-4 max-w-xs"
          placeholder="Filter by prefix, e.g. cash."
          value={prefix}
          onChange={(e) => setPrefix(e.target.value)}
        />
        <Load state={facts}>
          {(list) => (
            <>
              <p className="mb-2 text-sm text-text-muted">
                As of {list.as_of} · {list.pack_ref} · {list.total} facts
              </p>
              <div className="flex flex-col gap-1">
                {list.facts.map((f) => (
                  <div key={f.id} className="flex items-center gap-3 text-sm">
                    <Button size="xs" variant="outline" onClick={() => setFactId(f.id)}>
                      Explain
                    </Button>
                    <span className="font-mono text-xs">{f.id}</span>
                    <span className="tabular-nums">{f.display}</span>
                  </div>
                ))}
              </div>
            </>
          )}
        </Load>
      </Section>
    </>
  );
}
