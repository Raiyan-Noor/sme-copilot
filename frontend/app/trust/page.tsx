"use client";

import { useState } from "react";

import { useBusiness } from "@/components/business-context";
import { RedteamPanel } from "@/components/copilot/redteam-panel";
import { Load, PageHeader, Section } from "@/components/data";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { api } from "@/lib/api";
import { PREVIEW_REDTEAM } from "@/lib/mock/redteam";
import { useApi } from "@/lib/use-api";
import { cn } from "@/lib/utils";

const PAGE = 50;

const TABS = [
  { value: "audit", label: "Audit log" },
  { value: "redteam", label: "Red-team" },
] as const;
type Tab = (typeof TABS)[number]["value"];

export default function TrustPage() {
  const [tab, setTab] = useState<Tab>("audit");
  return (
    <div className="mx-auto w-full max-w-[880px]">
      <PageHeader title="Trust" description="What the assistant may do, and proof of what it did" />
      <div role="tablist" className="mb-6 flex gap-6 border-b border-border">
        {TABS.map((t) => (
          <button
            key={t.value}
            role="tab"
            type="button"
            aria-selected={tab === t.value}
            onClick={() => setTab(t.value)}
            className={cn(
              "-mb-px border-b-2 pb-2.5 text-sm font-medium transition-colors",
              tab === t.value ? "border-brand-primary text-text" : "border-transparent text-text-muted hover:text-text",
            )}
          >
            {t.label}
          </button>
        ))}
      </div>
      {/* Red-team results are preview data until `make redteam` writes docs/results/redteam.json (prompt 15). */}
      {tab === "audit" ? <AuditTab /> : <RedteamPanel results={PREVIEW_REDTEAM} />}
    </div>
  );
}

function AuditTab() {
  const { session } = useBusiness();
  const [kind, setKind] = useState("");
  const [offset, setOffset] = useState(0);
  const verify = useApi(`verify:${session}`, api.auditVerify);
  const audit = useApi(`audit:${session}:${kind}:${offset}`, () => api.audit({ kind, offset, limit: PAGE }));

  return (
    <>
      <Section title="Audit chain" description="GET /audit/verify">
        <Load state={verify}>
          {(v) => (
            <div className="flex flex-col gap-2 text-sm">
              <div className="flex items-center gap-3">
                <Badge variant={v.ok ? "secondary" : "destructive"}>{v.ok ? "Chain verified" : "Chain broken"}</Badge>
                <span className="tabular-nums">{v.entries} entries</span>
                <Button size="sm" variant="outline" onClick={verify.reload}>
                  Verify again
                </Button>
              </div>
              <p className="font-mono text-xs break-all">
                Head #{v.head.seq}: {v.head.hash}
              </p>
              {!v.ok && (
                <p className="text-danger">
                  First bad entry: #{v.first_bad_seq} ({v.reason})
                </p>
              )}
            </div>
          )}
        </Load>
      </Section>
      <Section title="Audit log" description="GET /audit">
        <Input
          className="mb-4 max-w-xs"
          placeholder="Filter by kind, e.g. gateway."
          value={kind}
          onChange={(e) => {
            setKind(e.target.value);
            setOffset(0);
          }}
        />
        <Load state={audit}>
          {(page) => (
            <>
              <div className="mb-2 flex items-center gap-3 text-sm text-text-muted">
                <span className="tabular-nums">
                  {page.total === 0 ? 0 : page.offset + 1} to {page.offset + page.entries.length} of {page.total}
                </span>
                <Button size="xs" variant="outline" disabled={offset === 0} onClick={() => setOffset(offset - PAGE)}>
                  Previous
                </Button>
                <Button
                  size="xs"
                  variant="outline"
                  disabled={offset + PAGE >= page.total}
                  onClick={() => setOffset(offset + PAGE)}
                >
                  Next
                </Button>
              </div>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>#</TableHead>
                    <TableHead>Date</TableHead>
                    <TableHead>Kind</TableHead>
                    <TableHead>Data</TableHead>
                    <TableHead>Hash</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {page.entries.map((e) => (
                    <TableRow key={e.seq}>
                      <TableCell className="tabular-nums">{e.seq}</TableCell>
                      <TableCell className="tabular-nums">{e.date}</TableCell>
                      <TableCell className="font-mono text-xs">{e.kind}</TableCell>
                      <TableCell className="max-w-md truncate font-mono text-xs" title={JSON.stringify(e.data)}>
                        {JSON.stringify(e.data)}
                      </TableCell>
                      <TableCell className="font-mono text-xs">{e.hash.slice(0, 12)}</TableCell>
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
