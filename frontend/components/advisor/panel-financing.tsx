"use client";

import { ChevronRight, Download, FileText } from "lucide-react";
import { useState } from "react";

import { useBusinessKey } from "@/components/business-context";
import { Button } from "@/components/kc/button";
import { FactNumber, FactText } from "@/components/kc/fact";
import { FactorBar } from "@/components/kc/misc";
import { StatusPill } from "@/components/kc/status-pill";
import { Skeleton } from "@/components/ui/skeleton";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import { ruleLabel, shortDate } from "@/lib/format";
import type { Fact, FinancingResponse, PassportExportSummary, PassportResponse, ProductMatch } from "@/lib/types";
import { useApi } from "@/lib/use-api";

import { PanelFrame } from "./detail-panel";
import { shortHash, VerifyOnchain } from "./onchain";
import { useAdvisor } from "./state";

const num = (v: unknown) => (typeof v === "number" ? v : 0);

function Offer({ p, facts, defaultOpen }: { p: ProductMatch; facts: Record<string, Fact>; defaultOpen: boolean }) {
  const { addPending, openApproval, toast } = useAdvisor();
  const { id } = useBusinessKey("offer");
  const [open, setOpen] = useState(defaultOpen);
  const [busy, setBusy] = useState(false);
  const pass = p.rules.filter((r) => r.passed).length;
  const f = (fid: string) => facts[fid];

  const prepare = async () => {
    setBusy(true);
    try {
      const r = await api.prepareApplication(id, { product_id: p.product_id });
      const approvalId = r.decision.approval?.approval_id;
      if (r.decision.status === "pending_approval" && approvalId) {
        addPending([approvalId]);
        openApproval({
          approvalId,
          context: (
            <>
              {p.name} from {p.lender}, for the repayment-safe amount of <FactNumber fact={f(p.safe_amount_fact_id)} />.
              The draft and your Readiness Passport go with it.
            </>
          ),
        });
      } else {
        toast({
          variant: "danger",
          title: "Application not prepared",
          description: ruleLabel(r.decision.rule ?? r.decision.status),
        });
      }
    } catch (e) {
      toast({ variant: "danger", title: "Application not prepared", description: errorMessage(e) });
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="ka-offer">
      <div className="ka-offer__top">
        <div>
          <div className="kc-caption">{p.type}</div>
          <div className="kc-section-title">{p.name}</div>
          <div className="kc-caption">{p.lender}</div>
        </div>
        <StatusPill
          status={p.eligible ? "fits" : "doesnt-fit"}
          size="sm"
          label={p.status === "not_safe" ? "Not repayment-safe" : undefined}
        />
      </div>
      <dl className="ka-terms">
        <div>
          <dt>Safe amount</dt>
          <dd className="big">
            <FactNumber fact={f(p.safe_amount_fact_id)} />
          </dd>
        </div>
        <div>
          <dt>Monthly rate</dt>
          <dd>
            <FactNumber fact={f(p.monthly_rate_fact_id)} />
          </dd>
        </div>
        <div>
          <dt>Instalment</dt>
          <dd>
            <FactNumber fact={f(p.installment_fact_id)} />
          </dd>
        </div>
        <div>
          <dt>Term</dt>
          <dd>
            <FactNumber fact={f(p.term_fact_id)} />
          </dd>
        </div>
      </dl>
      <p className="kc-caption" style={{ margin: 0 }}>
        {p.fit_reason}
      </p>
      <div>
        <button
          type="button"
          className="ka-fold"
          style={{ marginLeft: -12 }}
          aria-expanded={open}
          onClick={() => setOpen((x) => !x)}
        >
          <span>
            {pass} of {p.rules.length} rules pass
          </span>
          <span className="chev" style={{ transform: open ? "rotate(90deg)" : "none" }}>
            <ChevronRight size={16} strokeWidth={1.5} aria-hidden />
          </span>
        </button>
        {open
          ? p.rules.map((r) => (
              <div className="ka-rule" key={r.rule}>
                <span className="ka-rule__l" style={{ minWidth: 0 }}>
                  {r.label}
                  <div className="ka-rule__v">
                    <FactNumber fact={f(r.metric_fact_id)} />, {r.op === ">=" ? "needs at least" : "needs at most"}{" "}
                    <FactNumber fact={f(r.threshold_fact_id)} />
                  </div>
                </span>
                <span className="ka-rule__r">
                  <StatusPill size="sm" status={r.passed ? "fits" : "doesnt-fit"} label={r.passed ? "Pass" : "Fail"} />
                </span>
              </div>
            ))
          : null}
      </div>
      {p.eligible ? (
        <div>
          <Button variant="secondary" size="sm" iconLeft={FileText} loading={busy} onClick={prepare}>
            Prepare application
          </Button>
        </div>
      ) : null}
    </div>
  );
}

export function FinancingPanel() {
  const { toast } = useAdvisor();
  const { id, key } = useBusinessKey("financing");
  const fin = useApi<FinancingResponse>(key && `${key}:financing`, () => api.financing(id));
  const pp = useApi<PassportResponse>(key && `${key}:passport`, () => api.passport(id));
  const exports = useApi<PassportExportSummary[]>(key && `${key}:passport-exports`, () => api.passportExports(id));
  const [exporting, setExporting] = useState(false);
  const lastExport = exports.data?.length ? exports.data[exports.data.length - 1] : null;

  const products = [...(fin.data?.match.products ?? [])].sort((a, b) => Number(b.eligible) - Number(a.eligible));
  const fits = products.filter((p) => p.eligible).length;
  const facts = { ...(fin.data?.facts ?? {}), ...(pp.data?.facts ?? {}) };
  const passport = pp.data?.passport;

  const exportPassport = async () => {
    setExporting(true);
    try {
      const r = await api.exportPassport(id);
      toast({
        variant: "success",
        title: "Passport exported",
        description: `Fingerprint ${r.sha256.slice(0, 12)}…, recorded in the audit log and anchored on the testnet`,
      });
      exports.reload();
    } catch (e) {
      toast({ variant: "danger", title: "Could not export the passport", description: errorMessage(e) });
    } finally {
      setExporting(false);
    }
  };

  return (
    <PanelFrame
      title="Financing"
      description={fin.data ? `${fits} fit · ${products.length - fits} don't fit` : "Checked against your cash flow"}
      footer={
        <span className="kc-caption">
          The lender decides. This is not financial advice. Products and terms are synthetic.
        </span>
      }
    >
      {fin.error !== undefined || pp.error !== undefined ? (
        <p className="ka-text" style={{ color: "var(--danger)" }}>
          Could not load financing: {errorMessage(fin.error ?? pp.error)}
        </p>
      ) : !fin.data || !passport ? (
        <Skeleton className="h-96 w-full" />
      ) : (
        <div className="ka-stack">
          <p className="ka-advise">
            I compare offers against your cash flow and size each one so the repayments stay safe. I never apply on my
            own: sending an application always waits for your signature.
          </p>
          <section className="ka-passport" aria-label="Readiness Passport">
            <div className="ka-passport__top">
              <div>
                <div className="kc-section-title">Readiness Passport</div>
                <div className="kc-caption">What lenders ask for, kept up to date</div>
              </div>
              <span className="kc-label">
                {passport.band_label} · <FactNumber fact={facts[passport.score_fact_id]} />
              </span>
            </div>
            <div className="ka-stack" style={{ gap: 16 }}>
              {passport.factors.map((fa) => (
                <FactorBar
                  key={fa.factor}
                  label={fa.label}
                  value={num(facts[fa.score_fact_id]?.value)}
                  max={1}
                  tone={fa.status === "strong" ? "brand" : fa.status === "fair" ? "gold" : "danger"}
                  valueLabel={<FactNumber fact={facts[fa.raw_fact_id]} />}
                  hint={<FactText text={fa.reason} facts={facts} />}
                />
              ))}
            </div>
            {passport.path_to_eligibility.length || passport.next_band_label ? (
              <div className="ka-sec" style={{ gap: 8 }}>
                <div className="kc-label">
                  {passport.next_band_label
                    ? `What would move you up to ${passport.next_band_label}`
                    : "What would help"}
                </div>
                {passport.path_to_eligibility.map((s, i) => (
                  <div key={i} className="ka-text" style={{ fontSize: 14 }}>
                    <FactText text={s.text} facts={facts} />
                  </div>
                ))}
                {passport.reasons.map((r, i) => (
                  <div key={`r${i}`} className="kc-caption">
                    <FactText text={r} facts={facts} />
                  </div>
                ))}
              </div>
            ) : null}
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
              <Button variant="ghost" size="sm" iconLeft={Download} loading={exporting} onClick={exportPassport}>
                Export passport
              </Button>
            </div>
            {lastExport ? (
              <div className="ka-sec" style={{ gap: 4 }}>
                <span className="kc-caption">
                  Last export {shortDate(lastExport.as_of)}, fingerprint{" "}
                  <span style={{ fontFamily: "var(--font-code)" }}>{shortHash(lastExport.sha256, 12)}</span>. A lender
                  can check the file against the testnet.
                </span>
                <VerifyOnchain
                  key={lastExport.sha256}
                  check={() => api.passportOnchain(id, lastExport.sha256)}
                />
              </div>
            ) : null}
          </section>
          <section>
            {products.map((p, i) => (
              <Offer key={p.product_id} p={p} facts={facts} defaultOpen={i === 0} />
            ))}
          </section>
        </div>
      )}
    </PanelFrame>
  );
}
