"use client";

import { useBusinessKey } from "@/components/business-context";
import { Load, NotYetAvailable, PageHeader, Section } from "@/components/data";
import { api } from "@/lib/api";
import { useApi } from "@/lib/use-api";

export default function FinancingPage() {
  const { id, key } = useBusinessKey("business");
  const detail = useApi(key, () => api.business(id));

  return (
    <>
      <PageHeader title="Financing" />
      <Section title="Financing matches and Readiness Passport">
        <NotYetAvailable what="Financing matching and the Readiness Passport" prompt="13" />
      </Section>
      <Section title="Business on file" description="GET /businesses/{id}">
        <Load state={detail}>
          {(b) => (
            <dl className="grid grid-cols-[max-content_1fr] gap-x-6 gap-y-1 text-sm">
              <dt className="text-text-muted">Name</dt>
              <dd>{b.name}</dd>
              <dt className="text-text-muted">Skill Pack</dt>
              <dd>{b.pack_id}</dd>
              <dt className="text-text-muted">Currency</dt>
              <dd>{b.currency}</dd>
              <dt className="text-text-muted">Synthetic data</dt>
              <dd>{b.synthetic ? "yes" : "no"}</dd>
              <dt className="text-text-muted">Transactions</dt>
              <dd className="tabular-nums">{b.transactions}</dd>
              <dt className="text-text-muted">Scheduled items</dt>
              <dd className="tabular-nums">{b.scheduled_items}</dd>
              <dt className="text-text-muted">Accounts</dt>
              <dd>{b.accounts.map((a) => `${a.name} (${a.currency})`).join(", ")}</dd>
            </dl>
          )}
        </Load>
      </Section>
    </>
  );
}
