"use client";

import { Download, ExternalLink, RotateCw } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { useBusinessKey } from "@/components/business-context";
import { Button } from "@/components/kc/button";
import { Table } from "@/components/kc/misc";
import { StatusPill } from "@/components/kc/status-pill";
import { Skeleton } from "@/components/ui/skeleton";
import { api, transactionStream, type TransactionQuery } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import { money, shortDate } from "@/lib/format";
import type { TransactionRow } from "@/lib/types";
import { useApi } from "@/lib/use-api";

import { PanelFrame } from "./detail-panel";
import { useAdvisor } from "./state";

const PAGE = 50;

const SOURCE_LABEL: Record<TransactionRow["source"] & string, string> = {
  import: "CSV import",
  payment: "Payment (SandboxPay)",
};

function MoneyCell({ row }: { row: TransactionRow }) {
  const inflow = row.amount_minor >= 0;
  return (
    <span style={{ color: inflow ? "var(--success)" : "var(--text)", fontVariantNumeric: "tabular-nums" }}>
      {inflow ? "+" : ""}
      {money(row.amount_minor, row.currency)}
    </span>
  );
}

function TransactionDetail({ id, onBack }: { id: string; onBack: () => void }) {
  const { id: businessId, key } = useBusinessKey("tx-detail");
  const row = useApi<TransactionRow>(key && `${key}:${id}`, () => api.transaction(businessId, id));

  return (
    <PanelFrame
      title="Transaction"
      description={row.data ? shortDate(row.data.posted_on) : undefined}
      footer={
        <Button variant="ghost" size="sm" onClick={onBack}>
          Back to all transactions
        </Button>
      }
    >
      {row.error !== undefined ? (
        <p className="ka-text" style={{ color: "var(--danger)" }}>
          Could not load this transaction: {errorMessage(row.error)}
        </p>
      ) : !row.data ? (
        <Skeleton className="h-64 w-full" />
      ) : (
        <div className="ka-stack" style={{ gap: 24 }}>
          <div className="ka-trace-sum">
            <span className="kc-label" style={{ color: "var(--text-muted)", fontWeight: 400 }}>
              {row.data.description}
            </span>
            <span className="kc-display-number">
              <MoneyCell row={row.data} />
            </span>
            <span className="kc-caption">Running balance {money(row.data.running_balance_minor, row.data.currency)}</span>
          </div>
          <dl className="ka-tx-detail">
            <dt>Date</dt>
            <dd>{shortDate(row.data.posted_on)}</dd>
            <dt>Counterparty</dt>
            <dd>{row.data.counterparty || "—"}</dd>
            <dt>Category</dt>
            <dd>{row.data.category || "Uncategorized"}</dd>
            <dt>Source</dt>
            <dd>{SOURCE_LABEL[row.data.source ?? "import"] ?? row.data.source}</dd>
            <dt>Status</dt>
            <dd>
              <StatusPill
                size="sm"
                status={row.data.status === "settled" ? "executed" : "neutral"}
                label={row.data.status ?? "settled"}
              />
            </dd>
            <dt>Account</dt>
            <dd style={{ fontFamily: "var(--font-code)" }}>{row.data.account_id}</dd>
            <dt>Row ID</dt>
            <dd style={{ fontFamily: "var(--font-code)" }}>{row.data.id}</dd>
            <dt>Import</dt>
            <dd style={{ fontFamily: "var(--font-code)" }}>{row.data.import_id}</dd>
          </dl>
          <div className="kc-caption">
            {row.data.source === "payment" ? (
              <>
                This row was posted when the payment provider&apos;s signed webhook said the payment settled. Its
                receipt fingerprint goes into the next anchoring batch; verify it on-chain from the payment in the
                Payments tab.
              </>
            ) : (
              <>
                This row came in through a CSV statement import, logged to the audit chain at the time of import. A
                dedicated on-chain verify link for individual rows isn&apos;t built yet; the audit log&apos;s head
                (which covers every row) is anchored and verifiable from the Trust tab.
              </>
            )}
          </div>
        </div>
      )}
    </PanelFrame>
  );
}

export function TransactionsPanel({ openId }: { openId?: string }) {
  const { pushPanel, popPanel, toast, ledgerVersion } = useAdvisor();
  const { id: businessId, key } = useBusinessKey("transactions");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [direction, setDirection] = useState<"all" | "in" | "out">("all");
  const [search, setSearch] = useState("");
  const [count, setCount] = useState(PAGE);
  const [newIds, setNewIds] = useState<Set<string>>(new Set());
  const [exporting, setExporting] = useState(false);

  const query = useMemo<TransactionQuery>(
    () => ({
      date_from: dateFrom || undefined,
      date_to: dateTo || undefined,
      search: search.trim() || undefined,
      direction: direction === "all" ? undefined : direction,
      order: "desc",
      offset: 0,
      limit: count,
    }),
    [dateFrom, dateTo, search, direction, count],
  );
  const page = useApi(key && `${key}:tx:${ledgerVersion}:${JSON.stringify(query)}`, () =>
    api.transactions(businessId, query),
  );
  const latest = useApi(key && `${key}:tx-latest:${ledgerVersion}`, () => api.transactions(businessId, { limit: 1 }));
  const rows = page.data?.items ?? [];

  useEffect(() => {
    if (!key || openId) return;
    const controller = new AbortController();
    void (async () => {
      try {
        for await (const { event, data } of transactionStream(businessId, controller.signal)) {
          if (event === "transaction") {
            const row = data as TransactionRow;
            setNewIds((s) => new Set(s).add(row.id));
            setTimeout(() => setNewIds((s) => { const n = new Set(s); n.delete(row.id); return n; }), 2500);
            page.reload();
            latest.reload();
            toast({ title: "New transaction", description: row.description });
          }
        }
      } catch {
        // Connection closed (navigated away or aborted); nothing to show the owner.
      }
    })();
    return () => controller.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, openId]);

  if (openId) {
    return <TransactionDetail id={openId} onBack={popPanel} />;
  }

  const exportCsv = async () => {
    setExporting(true);
    try {
      const blob = await api.exportTransactions(businessId, { ...query, limit: undefined, offset: undefined });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "transactions.csv";
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      toast({ variant: "danger", title: "Could not export", description: errorMessage(e) });
    } finally {
      setExporting(false);
    }
  };

  return (
    <PanelFrame
      title="Transactions"
      description={
        latest.data?.items[0]
          ? `Current balance ${money(latest.data.items[0].running_balance_minor, latest.data.items[0].currency)}`
          : "Every ledger row, newest first"
      }
      footer={
        <Button variant="secondary" size="sm" iconLeft={Download} loading={exporting} onClick={exportCsv}>
          Export filtered view
        </Button>
      }
    >
      <div className="ka-stack" style={{ gap: 20 }}>
        <div className="ka-tx-filters">
          <input
            className="ka-tx-search"
            type="search"
            placeholder="Search description or counterparty"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            aria-label="Search transactions"
          />
          <input
            type="date"
            value={dateFrom}
            onChange={(e) => setDateFrom(e.target.value)}
            aria-label="From date"
          />
          <input type="date" value={dateTo} onChange={(e) => setDateTo(e.target.value)} aria-label="To date" />
          <select
            value={direction}
            onChange={(e) => setDirection(e.target.value as "all" | "in" | "out")}
            aria-label="Money in or out"
          >
            <option value="all">Money in and out</option>
            <option value="in">Money in</option>
            <option value="out">Money out</option>
          </select>
        </div>
        {page.error !== undefined ? (
          <p className="ka-text" style={{ color: "var(--danger)" }}>
            Could not load transactions: {errorMessage(page.error)}
          </p>
        ) : !page.data ? (
          <Skeleton className="h-96 w-full" />
        ) : (
          <>
            <Table<TransactionRow>
              density="compact"
              rowKey={(r) => r.id}
              rows={rows}
              onRowClick={(r) => pushPanel({ view: "transactions", txId: r.id })}
              rowClassName={(r) => (newIds.has(r.id) ? "kc-table__row--new" : undefined)}
              empty="No transactions match these filters."
              columns={[
                {
                  key: "date",
                  header: "Date",
                  width: 76,
                  render: (r) => shortDate(r.posted_on),
                },
                {
                  key: "what",
                  header: "Description",
                  render: (r) => (
                    <div>
                      <div style={{ fontWeight: 500 }}>{r.description}</div>
                      <div className="kc-caption">
                        {r.counterparty || "—"} · {r.category || "Uncategorized"}
                      </div>
                    </div>
                  ),
                },
                {
                  key: "source",
                  header: "Source",
                  render: (r) => <span className="kc-caption">{SOURCE_LABEL[r.source ?? "import"] ?? r.source}</span>,
                },
                {
                  key: "status",
                  header: "Status",
                  render: (r) => (
                    <StatusPill
                      size="sm"
                      status={r.status === "settled" ? "executed" : "neutral"}
                      label={r.status ?? "settled"}
                    />
                  ),
                },
                { key: "amount", header: "Amount", align: "right", render: (r) => <MoneyCell row={r} /> },
                {
                  key: "balance",
                  header: "Balance",
                  align: "right",
                  render: (r) => money(r.running_balance_minor, r.currency),
                },
              ]}
            />
            {page.data.total > count ? (
              <div style={{ display: "flex", justifyContent: "center" }}>
                <Button variant="ghost" size="sm" iconLeft={RotateCw} onClick={() => setCount((c) => c + PAGE)}>
                  Show more ({page.data.total - count} more)
                </Button>
              </div>
            ) : null}
            <div className="kc-caption">
              Amounts are integer minor units from the ledger, formatted for display only. Counterparty names have
              PII already replaced with tokens before they ever reach this screen.{" "}
              <Button
                variant="ghost"
                size="sm"
                iconRight={ExternalLink}
                onClick={() => pushPanel({ view: "trust", tab: "audit" })}
              >
                See the audit log
              </Button>
            </div>
          </>
        )}
      </div>
    </PanelFrame>
  );
}
