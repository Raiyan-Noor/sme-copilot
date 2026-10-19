"use client";

import { Anchor, CircleAlert, CircleCheck, Link2, PenLine, Signature } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { useBusiness, useBusinessKey } from "@/components/business-context";
import { Button } from "@/components/kc/button";
import { Table, Tabs, TierRow } from "@/components/kc/misc";
import { Sheet } from "@/components/kc/sheet";
import { StatusPill, decisionPill } from "@/components/kc/status-pill";
import { Skeleton } from "@/components/ui/skeleton";
import { APP_NAME } from "@/config/app";
import { api, ApiError } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import { money, ruleLabel, sentence, shortDate, toolShort, toolTitle } from "@/lib/format";
import { ensureEnrolled, signMessage } from "@/lib/owner-key";
import type {
  AnchorStatus,
  AuditEntry,
  AuditVerifyResult,
  LimitsView,
  RedteamReport,
  StandingMandateDraft,
  T2Limit,
} from "@/lib/types";
import { useApi } from "@/lib/use-api";

import { PanelFrame } from "./detail-panel";
import { ExplorerLink, OnchainPill, shortHash, VerifyOnchain } from "./onchain";
import { useAdvisor, type TrustTab } from "./state";

const DAYS = 30;

/**
 * Sign a T2 standing mandate in the browser (invariant 6). The server drafts the payload (terms hash, fresh nonce,
 * expiry), the owner reads it, and only the signature over its canonical message and the public key are sent. The
 * gateway refuses terms above the policy.yaml cap, so the cap shown here can only be lowered, never raised.
 */
function MandateSheet({
  limit,
  currency,
  onClose,
  onSigned,
}: {
  limit: T2Limit;
  currency: string;
  onClose: () => void;
  onSigned: () => void;
}) {
  const { business } = useBusiness();
  const { toast } = useAdvisor();
  const id = business?.id ?? "";
  const [chosen, setChosen] = useState<string[]>(limit.active?.allowlist ?? limit.candidates.map((c) => c.id));
  const [draft, setDraft] = useState<StandingMandateDraft | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const who = limit.allowlist_arg === "customer_id" ? "customers" : "payees";

  const review = async () => {
    setBusy(true);
    setError(null);
    try {
      setDraft(
        await api.draftMandate(id, {
          action: limit.tool,
          terms: { max_amount_minor: limit.policy_max_amount_minor, allowlist: chosen },
          days: DAYS,
        }),
      );
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  const sign = async () => {
    if (!draft) return;
    setBusy(true);
    setError(null);
    try {
      await ensureEnrolled(id);
      const { signature, publicKey } = await signMessage(draft.message);
      const r = await api.signMandate(id, {
        payload: draft.payload,
        terms: draft.terms,
        signature,
        public_key: publicKey,
      });
      if (r.accepted) {
        toast({
          variant: "success",
          title: "Limit signed",
          description: `${toolShort(limit.tool)}, mandate ${r.mandate?.id ?? ""}`,
        });
        onSigned();
        onClose();
      } else {
        setError(`The gateway refused it: ${ruleLabel(r.rule ?? "denied")}.`);
      }
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Sheet
      open
      onClose={onClose}
      title={`Sign a limit: ${toolShort(limit.tool)}`}
      description="Within this limit I act on my own. Anything above it waits for you."
      footer={
        draft ? (
          <>
            <Button iconLeft={PenLine} loading={busy} onClick={sign}>
              Sign and approve
            </Button>
            <Button variant="secondary" onClick={() => setDraft(null)} disabled={busy}>
              Change
            </Button>
          </>
        ) : (
          <Button loading={busy} disabled={chosen.length === 0} onClick={review}>
            Review what you sign
          </Button>
        )
      }
    >
      <div className="ka-stack" style={{ gap: 24 }}>
        <dl className="kc-approval__facts">
          <div className="kc-approval__fact">
            <dt>Each action up to</dt>
            <dd>{money(limit.policy_max_amount_minor, currency)}</dd>
          </div>
          <div className="kc-approval__fact">
            <dt>Lasts</dt>
            <dd>{DAYS} days</dd>
          </div>
          {limit.frequency ? (
            <div className="kc-approval__fact">
              <dt>How often</dt>
              <dd>
                At most {limit.frequency.max} per {sentence(limit.frequency.per).toLowerCase().replace(/ id$/, "")}{" "}
                every {limit.frequency.window_days} days
              </dd>
            </div>
          ) : null}
        </dl>
        <section className="ka-sec">
          <h3 className="kc-label" style={{ color: "var(--text-muted)" }}>
            Which {who} it covers
          </h3>
          {limit.candidates.length === 0 ? <p className="kc-caption">No {who} on file yet.</p> : null}
          {limit.candidates.map((c) => (
            <label key={c.id} className="ka-check" style={{ cursor: draft ? "default" : "pointer" }}>
              <input
                type="checkbox"
                disabled={!!draft}
                checked={chosen.includes(c.id)}
                onChange={(e) => setChosen((x) => (e.target.checked ? [...x, c.id] : x.filter((y) => y !== c.id)))}
              />
              <span>{c.name ?? c.id}</span>
              <span className="s">{c.id}</span>
            </label>
          ))}
        </section>
        {draft ? (
          <section className="ka-sec">
            <h3 className="kc-label" style={{ color: "var(--text-muted)" }}>
              What you sign
            </h3>
            <dl
              className="ka-mail__hdr"
              style={{
                borderBottom: 0,
                paddingBottom: 0,
                fontFamily: "var(--font-code)",
                gridTemplateColumns: "88px minmax(0,1fr)",
              }}
            >
              <dt>action</dt>
              <dd>{draft.payload.action}</dd>
              <dt>args_hash</dt>
              <dd>{draft.payload.args_hash}</dd>
              <dt>nonce</dt>
              <dd>{draft.payload.nonce}</dd>
              <dt>expiry</dt>
              <dd>{shortDate(draft.payload.expiry)}</dd>
            </dl>
          </section>
        ) : null}
        {error ? (
          <p className="ka-text" style={{ color: "var(--danger)" }} role="alert">
            {error}
          </p>
        ) : null}
      </div>
    </Sheet>
  );
}

function LimitsTab() {
  const { id, key } = useBusinessKey("limits");
  const limits = useApi<LimitsView>(key, () => api.limits(id));
  const [editing, setEditing] = useState<T2Limit | null>(null);
  const l = limits.data;
  if (limits.error !== undefined) {
    return (
      <p className="ka-text" style={{ color: "var(--danger)" }}>
        Could not load your limits: {errorMessage(limits.error)}
      </p>
    );
  }
  if (!l) return <Skeleton className="h-96 w-full" />;
  return (
    <div className="ka-stack">
      <section className="ka-sec" style={{ gap: 4 }}>
        <span className="kc-caption">
          Nothing above these limits happens without your signature. Signatures are made with the key on this device;
          the server only checks them.
        </span>
        <div>
          <TierRow
            tier={1}
            name="Look and compute"
            mode="auto"
            description="Reads your accounts and works out figures. It cannot move money."
            tools={l.t1_tools.map(toolShort)}
          />
          {l.t2.map((t) => (
            <TierRow
              key={t.tool}
              tier={2}
              name={toolShort(t.tool)}
              mode={t.active ? "auto" : "approval"}
              description={
                t.active
                  ? `Acts on its own for the ${t.active.allowlist.length} ${t.allowlist_arg === "customer_id" ? "customers" : "payees"} you chose.`
                  : "Not signed yet, so nothing runs on its own. Each one waits for you."
              }
              limit={money(t.active?.max_amount_minor ?? t.policy_max_amount_minor, l.currency)}
              tools={[toolTitle(t.tool)]}
              signedNote={
                t.active ? (
                  <>
                    <Signature size={14} strokeWidth={1.5} aria-hidden />
                    Mandate {t.active.mandate_id}, signed {shortDate(t.active.signed_on)}, ends{" "}
                    {shortDate(t.active.expiry)}
                    <VerifyOnchain compact check={() => api.mandateOnchain(id, t.active!.mandate_id)} />
                  </>
                ) : undefined
              }
              onEdit={() => setEditing(t)}
              editLabel={t.active ? "Re-sign limit" : "Sign limit"}
            />
          ))}
          <TierRow
            tier={3}
            name="Needs your signature"
            mode="approval"
            description={`${APP_NAME} prepares it; you sign the exact details every time.`}
            tools={l.t3.map((t) => toolShort(t.tool))}
            signedNote={
              l.t3.some((t) => t.requires_out_of_band_call_script)
                ? "Bank detail changes also need a call on a number you already have."
                : undefined
            }
          />
          <TierRow
            tier={4}
            name="Never automated"
            mode="never"
            description="These tools do not exist. Requests get analysis only, and are logged."
            tools={l.t4_categories.map(toolShort)}
          />
        </div>
      </section>
      {editing ? (
        <MandateSheet limit={editing} currency={l.currency} onClose={() => setEditing(null)} onSigned={limits.reload} />
      ) : null}
    </div>
  );
}

const PAGE = 50;

/** The on-chain half of "Verify chain": the log recomputed here against each root anchored on the testnet. */
function OnchainRow({ result }: { result: AuditVerifyResult }) {
  const { ok, batches } = result.onchain;
  const latest = batches[0];
  const bad = batches.find((b) => b.status === "mismatch");
  const shown = bad ?? latest;
  const title =
    ok === true ? "Matches the testnet" : ok === false ? "Does not match the testnet" : "Not checked on-chain";
  const caption =
    ok === true
      ? `Recomputed from this log, the ${batches.length === 1 ? "root of the anchored batch equals" : `roots of ${batches.length} anchored batches equal`} the ${batches.length === 1 ? "one" : "ones"} on chain.`
      : ok === false
        ? `Batch ${bad?.batch_id}: ${bad?.reason ?? "the root differs"}. The log was changed after it was anchored.`
        : latest
          ? `${latest.reason ?? "The testnet could not be reached"}.`
          : "Nothing has been anchored yet. Use Anchor now on the On-chain tab.";
  const tone = ok === false ? { color: "var(--danger)" } : ok === null ? { color: "var(--text-muted)" } : undefined;
  return (
    <div className="ka-vrow">
      <span className="i" style={tone}>
        {ok === false ? <CircleAlert size={18} strokeWidth={1.5} /> : <Anchor size={18} strokeWidth={1.5} />}
      </span>
      <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
        <div className="t">{title}</div>
        <div className="kc-caption">{caption}</div>
        {shown?.explorer_url ? (
          <div className="kc-caption">
            <ExplorerLink url={shown.explorer_url} label={`Batch ${shown.batch_id} on the explorer`} />
          </div>
        ) : null}
      </div>
    </div>
  );
}

const TRIGGERS: Record<string, string> = {
  manual: "Anchor now",
  batch_size: "Regular batch",
  scenario_end: "End of day",
  owner_signed: "After your signature",
  passport_exported: "Passport exported",
};

const ANCHOR_RESULT: Record<string, [string, string]> = {
  queued: ["Anchoring", "The batch is on its way to the testnet."],
  confirmed: ["Anchored", "The batch's root is on the testnet."],
  already_queued: ["Already anchoring", "A batch is still on its way. Trying it again now."],
  up_to_date: ["Already anchored", "Nothing new since the last batch."],
  not_configured: ["Anchoring is off", "No testnet is configured on this server."],
  auto_off: ["Anchoring is off", "Automatic anchoring is off."],
};

/**
 * Anchoring (invariant 9): only a Merkle root of hashes goes on chain, in a 0-value transaction to itself on a
 * testnet. The server sends in the background, so this tab polls while a batch is on its way.
 */
function AnchorsTab() {
  const { session } = useBusiness();
  const { toast } = useAdvisor();
  const [status, setStatus] = useState<AnchorStatus | null>(null);
  const [error, setError] = useState<unknown>(undefined);
  const [busy, setBusy] = useState(false);
  const [tick, setTick] = useState(0);
  const refresh = useCallback(() => setTick((n) => n + 1), []);

  useEffect(() => {
    let live = true;
    api.anchors().then(
      (s) => {
        if (!live) return;
        setStatus(s);
        setError(undefined);
      },
      (e) => live && setError(e),
    );
    return () => {
      live = false;
    };
  }, [session, tick]);

  const waiting = (status?.queued ?? 0) > 0;
  useEffect(() => {
    if (!waiting) return;
    const t = setInterval(refresh, 4000);
    return () => clearInterval(t);
  }, [waiting, refresh]);

  const anchorNow = async () => {
    setBusy(true);
    try {
      const r = await api.anchorNow();
      const [title, description] = ANCHOR_RESULT[r.status];
      toast({ variant: r.status === "not_configured" ? "danger" : "success", title, description });
      refresh();
    } catch (e) {
      toast({ variant: "danger", title: "Could not anchor", description: errorMessage(e) });
    } finally {
      setBusy(false);
    }
  };

  if (error !== undefined && !status) {
    return (
      <p className="ka-text" style={{ color: "var(--danger)" }}>
        Could not load anchors: {errorMessage(error)}
      </p>
    );
  }
  if (!status) return <Skeleton className="h-64 w-full" />;
  return (
    <div className="ka-stack" style={{ gap: 20 }}>
      <div className="ka-sechead" style={{ alignItems: "center" }}>
        <span className="kc-caption">
          Fingerprints of the audit log, your signed limits and exported passports are published on the{" "}
          {status.chain_name} test network. Only fingerprints leave this server: no names, amounts or account details.
          Anyone can check them on a public explorer.
        </span>
        <Button variant="secondary" size="sm" iconLeft={Anchor} loading={busy} onClick={anchorNow}>
          Anchor now
        </Button>
      </div>
      {!status.configured ? (
        <p className="kc-caption" role="status">
          Sending is off on this server ({status.reason ?? "no testnet configured"}). Batches anchored earlier can
          still be verified.
        </p>
      ) : null}
      {status.batches.length === 0 ? (
        <p className="ka-text" style={{ color: "var(--text-muted)" }}>
          Nothing anchored yet.
        </p>
      ) : (
        <Table<AnchorStatus["batches"][number]>
          density="compact"
          rowKey={(b) => b.batch_id}
          rows={status.batches}
          columns={[
            {
              key: "batch",
              header: "Batch",
              render: (b) => {
                const n = (k: string) => b.leaves.filter((l) => l.kind === k).length;
                const parts = [
                  `log up to #${b.head_seq}`,
                  n("mandate") ? `${n("mandate")} signed ${n("mandate") === 1 ? "limit" : "limits"}` : "",
                  n("passport") ? `${n("passport")} ${n("passport") === 1 ? "passport" : "passports"}` : "",
                  n("skill") ? `${n("skill")} ${n("skill") === 1 ? "skill" : "skills"}` : "",
                ].filter(Boolean);
                return (
                  <div>
                    <div style={{ fontWeight: 500 }}>
                      {b.batch_id} · {TRIGGERS[b.trigger] ?? sentence(b.trigger)}
                    </div>
                    <div className="kc-caption">
                      {shortDate(b.created_on)} · {parts.join(", ")} · root{" "}
                      <span style={{ fontFamily: "var(--font-code)" }}>{shortHash(b.merkle_root, 12)}</span>
                      {b.block_number !== null ? ` · block ${b.block_number}` : ""}
                      {b.status !== "confirmed" && b.last_error ? ` · retrying: ${b.last_error}` : ""}
                    </div>
                    {b.explorer_url ? (
                      <div className="kc-caption">
                        <ExplorerLink url={b.explorer_url} />
                      </div>
                    ) : null}
                  </div>
                );
              },
            },
            {
              key: "status",
              header: "Status",
              align: "right",
              render: (b) => <OnchainPill status={b.status === "confirmed" ? "match" : "pending"} />,
            },
          ]}
        />
      )}
    </div>
  );
}

const providerName = (p: string) => ({ openai: "OpenAI", gemini: "Gemini" })[p] ?? sentence(p);

function auditWhat(e: AuditEntry): string {
  const tool = typeof e.data.tool === "string" ? ` · ${toolTitle(e.data.tool)}` : "";
  return `${sentence(e.kind)}${tool}`;
}

function auditStatus(e: AuditEntry) {
  const s = e.data.status;
  if (s === "executed" || s === "pending_approval" || s === "denied")
    return <StatusPill size="sm" status={decisionPill(s)} />;
  return null;
}

function AuditTab() {
  const { session } = useBusiness();
  const [count, setCount] = useState(PAGE);
  const [verify, setVerify] = useState<AuditVerifyResult | "running" | null>(null);
  // GET /audit returns newest first.
  const audit = useApi(`audit:${session}:${count}`, () => api.audit({ offset: 0, limit: count }));

  const run = async () => {
    setVerify("running");
    try {
      setVerify(await api.auditVerify());
    } catch {
      setVerify(null);
    }
  };

  return (
    <div className="ka-stack" style={{ gap: 20 }}>
      <div className="ka-sechead" style={{ alignItems: "center" }}>
        <span className="kc-caption">
          Each record is hashed and linked to the one before, so a changed or deleted record breaks the chain. The
          head of the chain is also anchored on a public testnet, so rewriting the whole log shows up too.
        </span>
        <Button variant="secondary" size="sm" iconLeft={Link2} loading={verify === "running"} onClick={run}>
          Verify chain
        </Button>
      </div>
      {verify && verify !== "running" ? (
        <div className="ka-verify" role="status">
          <div className="ka-vrow">
            <span className="i" style={verify.ok ? undefined : { color: "var(--danger)" }}>
              {verify.ok ? <CircleCheck size={18} strokeWidth={1.5} /> : <CircleAlert size={18} strokeWidth={1.5} />}
            </span>
            <div>
              <div className="t">{verify.ok ? "Chain intact" : "Chain broken"}</div>
              <div className="kc-caption">
                {verify.ok
                  ? `${verify.entries} records. Every hash links to the one before.`
                  : `First bad record #${verify.first_bad_seq}: ${verify.reason ?? "hash mismatch"}.`}
              </div>
            </div>
          </div>
          <OnchainRow result={verify} />
          <div className="ka-vrow">
            <span className="i">
              <Link2 size={18} strokeWidth={1.5} />
            </span>
            <div>
              <div className="t">Head of the log</div>
              <div className="kc-caption" style={{ overflowWrap: "anywhere", fontFamily: "var(--font-code)" }}>
                #{verify.head.seq} · {verify.head.hash}
              </div>
            </div>
          </div>
        </div>
      ) : null}
      {audit.error !== undefined ? (
        <p className="ka-text" style={{ color: "var(--danger)" }}>
          Could not load the audit log: {errorMessage(audit.error)}
        </p>
      ) : !audit.data ? (
        <Skeleton className="h-64 w-full" />
      ) : (
        <>
          <Table<AuditEntry>
            density="compact"
            rowKey={(e) => String(e.seq)}
            rows={audit.data.entries}
            columns={[
              {
                key: "what",
                header: "What",
                render: (e) => (
                  <div>
                    <div style={{ fontWeight: 500 }}>{auditWhat(e)}</div>
                    <div className="kc-caption">
                      {shortDate(e.date)} · #{e.seq}
                      {typeof e.data.provider === "string"
                        ? ` · ${e.data.provider}${typeof e.data.model === "string" ? `/${e.data.model}` : ""}`
                        : ""}
                      {typeof e.data.rule === "string" ? ` · ${ruleLabel(e.data.rule)}` : ""} · {e.hash.slice(0, 10)}…
                    </div>
                  </div>
                ),
              },
              { key: "status", header: "Status", align: "right", render: auditStatus },
            ]}
          />
          {audit.data.total > count ? (
            <div>
              <Button variant="ghost" size="sm" onClick={() => setCount((c) => c + PAGE)}>
                Show older records
              </Button>
            </div>
          ) : null}
        </>
      )}
    </div>
  );
}

function RedteamTab() {
  const { session } = useBusiness();
  const report = useApi<RedteamReport>(`redteam:${session}`, api.redteam);
  if (report.error instanceof ApiError && report.error.status === 404) {
    return (
      <p className="ka-text" style={{ color: "var(--text-muted)" }}>
        The attack suite has not run yet. Results appear here after `make redteam`.
      </p>
    );
  }
  if (report.error !== undefined) {
    return (
      <p className="ka-text" style={{ color: "var(--danger)" }}>
        Could not load red-team results: {errorMessage(report.error)}
      </p>
    );
  }
  const r = report.data;
  if (!r) return <Skeleton className="h-64 w-full" />;
  const ran = Object.entries(r.providers).filter(([, p]) => p.status === "ran");
  const notRun = Object.entries(r.providers).filter(([, p]) => p.status !== "ran");
  return (
    <div className="ka-stack" style={{ gap: 28 }}>
      <p className="ka-text" style={{ color: "var(--text-muted)" }}>
        An attack suite tries to trick {APP_NAME} into paying, moving or borrowing money it should not. Each attack must
        be stopped by code, not by the model choosing to refuse.
      </p>
      {ran.map(([name, p]) => (
        <section key={name} className="ka-stack" style={{ gap: 20 }}>
          <div className="ka-kpis2">
            <div className="kc-kpi kc-kpi--md">
              <div className="kc-kpi__label">Attacks stopped</div>
              <div className="kc-kpi__value">
                {p.attacks_blocked ?? 0} of {p.attacks_run ?? 0}
              </div>
              <div className="kc-kpi__foot">
                <span className="kc-caption">
                  {p.attack_variants_blocked ?? 0} of {p.attack_variants_run ?? 0} variants
                </span>
              </div>
            </div>
            <div className="kc-kpi kc-kpi--md">
              <div className="kc-kpi__label">Everyday tasks completed</div>
              <div className="kc-kpi__value">
                {p.tasks_succeeded ?? 0} of {p.tasks_run ?? 0}
              </div>
              <div className="kc-kpi__foot">
                <span className="kc-caption">so safety does not block real work</span>
              </div>
            </div>
          </div>
          <div className="kc-caption">
            {providerName(name)} · {r.mode} run · models{" "}
            {Object.keys(p.recorded_models ?? {}).join(", ") || "none recorded"}
            {r.commit ? ` · commit ${r.commit.slice(0, 7)}` : ""}
          </div>
          <ul className="ka-rt">
            {(p.attacks ?? []).map((a) => (
              <li key={a.id}>
                <div>
                  <div style={{ fontSize: 14, fontWeight: 500 }}>{a.name}</div>
                  <div className="kc-caption">
                    {a.caught_by?.length
                      ? `Caught by ${a.caught_by.map((c) => `${sentence(c.layer).toLowerCase()} (${sentence(c.rule).toLowerCase()})`).join(", ")}`
                      : "No defense recorded"}
                  </div>
                </div>
                <StatusPill
                  size="sm"
                  status={a.blocked ? "executed" : "blocked"}
                  label={a.blocked ? "Stopped" : "Got through"}
                />
              </li>
            ))}
            {Object.entries(r.pending_attacks ?? {}).map(([aid, what]) => (
              <li key={aid}>
                <div>
                  <div style={{ fontSize: 14, fontWeight: 500 }}>{what}</div>
                  <div className="kc-caption">Planned</div>
                </div>
                <StatusPill size="sm" status="neutral" />
              </li>
            ))}
          </ul>
        </section>
      ))}
      {notRun.map(([name, p]) => (
        <div key={name} className="kc-caption">
          {providerName(name)}: not run{p.reason ? ` (${p.reason})` : ""}.
        </div>
      ))}
    </div>
  );
}

export function TrustPanel({ tab }: { tab: TrustTab }) {
  const { setPanelTab } = useAdvisor();
  return (
    <PanelFrame title="Limits and trust" description={`What ${APP_NAME} may do, and proof of what it did`}>
      <div className="ka-stack" style={{ gap: 24 }}>
        <Tabs<TrustTab>
          value={tab}
          onValueChange={setPanelTab}
          items={[
            { value: "limits", label: "Limits and tiers" },
            { value: "audit", label: "Audit log" },
            { value: "anchors", label: "On-chain" },
            { value: "redteam", label: "Red-team" },
          ]}
        />
        {tab === "limits" ? (
          <LimitsTab />
        ) : tab === "audit" ? (
          <AuditTab />
        ) : tab === "anchors" ? (
          <AnchorsTab />
        ) : (
          <RedteamTab />
        )}
      </div>
    </PanelFrame>
  );
}
