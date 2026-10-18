"use client";

import { ApiError } from "@/lib/api";
import type { Fact } from "@/lib/types";
import type { ApiState } from "@/lib/use-api";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";

export function PageHeader({ title, description }: { title: string; description?: string }) {
  return (
    <div className="mb-6">
      <h1 className="text-2xl font-semibold">{title}</h1>
      {description && <p className="text-sm text-text-muted">{description}</p>}
    </div>
  );
}

export function Section({
  title,
  description,
  children,
}: {
  title: string;
  description?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <Card className="mb-6">
      <CardHeader>
        <CardTitle>{title}</CardTitle>
        {description && <CardDescription>{description}</CardDescription>}
      </CardHeader>
      <CardContent>{children}</CardContent>
    </Card>
  );
}

export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    const detail = typeof error.detail === "string" ? error.detail : JSON.stringify(error.detail);
    return `${error.status}: ${detail}`;
  }
  return error instanceof Error ? error.message : String(error);
}

/** Renders loading and error states for a fetch, and `children(data)` once it has loaded. */
export function Load<T>({ state, children }: { state: ApiState<T>; children: (data: T) => React.ReactNode }) {
  if (state.error !== undefined) {
    return <p className="text-sm text-danger">Could not load: {errorMessage(state.error)}</p>;
  }
  if (state.loading || state.data === undefined) return <Skeleton className="h-24 w-full" />;
  return <>{children(state.data)}</>;
}

/** Placeholder for a page whose backend endpoint has not been built yet. */
export function NotYetAvailable({ what, prompt }: { what: string; prompt: string }) {
  return (
    <p className="text-sm text-text-muted">
      {what} is not in the API yet (build prompt {prompt}). This page will fetch it once the endpoint exists.
    </p>
  );
}

/** A Fact's display text. Numbers on screen always come from a Fact computed in code (invariant 4). */
export function FactValue({ fact }: { fact: Fact | null | undefined }) {
  if (!fact) return <span className="text-text-muted">n/a</span>;
  return (
    <span className="tabular-nums" title={`${fact.id} · ${fact.computed_by}`}>
      {fact.display}
    </span>
  );
}

export function FactTable({ facts }: { facts: (Fact | null | undefined)[] }) {
  const rows = facts.filter((f): f is Fact => !!f);
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Fact</TableHead>
          <TableHead>Value</TableHead>
          <TableHead>Unit</TableHead>
          <TableHead>Computed by</TableHead>
          <TableHead>Source rows</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {rows.map((f) => (
          <TableRow key={f.id}>
            <TableCell className="font-mono text-xs">{f.id}</TableCell>
            <TableCell>
              <FactValue fact={f} />
            </TableCell>
            <TableCell>
              <Badge variant="outline">{f.unit}</Badge>
            </TableCell>
            <TableCell className="font-mono text-xs">{f.computed_by}</TableCell>
            <TableCell className="tabular-nums">{f.source_row_ids.length}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
