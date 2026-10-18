/**
 * Typed client for the FastAPI backend. The browser calls NEXT_PUBLIC_API_URL directly (no Next rewrites).
 *
 * Every protected route needs the demo passcode in `X-Passcode`. The owner types it once; it is kept in this
 * browser's localStorage and never sent anywhere except the API.
 */
import type {
  AdvanceRequest,
  ApprovalView,
  ApproveRequest,
  AuditPage,
  BusinessDetail,
  BusinessInfo,
  CashPosition,
  ClockState,
  Decision,
  FactList,
  FactTrace,
  ForecastResponse,
  Head,
  HealthResponse,
  IngestReport,
  KpiResponse,
  MandateResult,
  OwnerKey,
  OwnerKeyRequest,
  PackSummary,
  PackSwitch,
  PnlResponse,
  ProposedAction,
  StandingMandateDraft,
  StandingMandateDraftRequest,
  StandingMandateRequest,
  TransactionPage,
  VerifyResult,
} from "@/lib/types";

export const API_URL = (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000").replace(/\/+$/, "");

const PASSCODE_KEY = "passcode";
const PASSCODE_HEADER = "X-Passcode";
let memoryPasscode = "";

export function getPasscode(): string {
  try {
    return localStorage.getItem(PASSCODE_KEY) ?? "";
  } catch {
    return "";
  }
}

export function setPasscode(value: string): void {
  try {
    if (value) localStorage.setItem(PASSCODE_KEY, value);
    else localStorage.removeItem(PASSCODE_KEY);
  } catch {
    // Storage blocked (private window): the passcode lasts only for this page load.
  }
  memoryPasscode = value;
}

export class ApiError extends Error {
  constructor(
    public status: number,
    public detail: unknown,
  ) {
    super(typeof detail === "string" ? detail : `API error ${status}`);
  }
}

type Query = Record<string, string | number | undefined | null>;

async function request<T>(method: string, path: string, opts: { query?: Query; body?: unknown } = {}): Promise<T> {
  const url = new URL(API_URL + path);
  for (const [k, v] of Object.entries(opts.query ?? {})) {
    if (v !== undefined && v !== null && v !== "") url.searchParams.set(k, String(v));
  }
  const headers: Record<string, string> = { [PASSCODE_HEADER]: getPasscode() || memoryPasscode };
  let body: BodyInit | undefined;
  if (opts.body instanceof FormData) {
    body = opts.body;
  } else if (opts.body !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(opts.body);
  }
  const res = await fetch(url, { method, headers, body, cache: "no-store" });
  const text = await res.text();
  const data = text ? JSON.parse(text) : undefined;
  if (!res.ok) throw new ApiError(res.status, data?.detail ?? res.statusText);
  return data as T;
}

const enc = encodeURIComponent;
const biz = (id: string) => `/businesses/${enc(id)}`;

export const api = {
  health: () => request<HealthResponse>("GET", "/health"),

  // Businesses and packs
  businesses: () => request<BusinessInfo[]>("GET", "/businesses"),
  business: (id: string) => request<BusinessDetail>("GET", biz(id)),
  packs: () => request<PackSummary[]>("GET", "/packs"),
  switchPack: (id: string, body: PackSwitch) => request<BusinessInfo>("PUT", `${biz(id)}/pack`, { body }),

  // Ledger
  transactions: (
    id: string,
    q: {
      date_from?: string;
      date_to?: string;
      category?: string;
      account_id?: string;
      order?: "asc" | "desc";
      offset?: number;
      limit?: number;
    } = {},
  ) => request<TransactionPage>("GET", `${biz(id)}/transactions`, { query: q }),
  uploadStatement: (id: string, form: FormData) =>
    request<IngestReport>("POST", `${biz(id)}/statements`, { body: form }),

  // Facts and finance
  facts: (id: string, q: { prefix?: string; offset?: number; limit?: number } = {}) =>
    request<FactList>("GET", `${biz(id)}/facts`, { query: q }),
  explainFact: (id: string, factId: string, maxRows?: number) =>
    request<FactTrace>("GET", `${biz(id)}/facts/${enc(factId)}/explain`, { query: { max_rows: maxRows } }),
  pnl: (id: string, period: "month" | "week" = "month") =>
    request<PnlResponse>("GET", `${biz(id)}/pnl`, { query: { period } }),
  cash: (id: string) => request<CashPosition>("GET", `${biz(id)}/cash`),
  forecast: (id: string) => request<ForecastResponse>("GET", `${biz(id)}/forecast`),
  kpis: (id: string) => request<KpiResponse>("GET", `${biz(id)}/kpis`),

  // Gateway
  enrollOwnerKey: (id: string, body: OwnerKeyRequest) =>
    request<OwnerKey>("POST", `${biz(id)}/gateway/owner-key`, { body }),
  propose: (id: string, body: ProposedAction) => request<Decision>("POST", `${biz(id)}/gateway/propose`, { body }),
  approval: (id: string, approvalId: string) =>
    request<ApprovalView>("GET", `${biz(id)}/gateway/approvals/${enc(approvalId)}`),
  approve: (id: string, approvalId: string, body: ApproveRequest) =>
    request<Decision>("POST", `${biz(id)}/gateway/approvals/${enc(approvalId)}/approve`, { body }),
  draftMandate: (id: string, body: StandingMandateDraftRequest) =>
    request<StandingMandateDraft>("POST", `${biz(id)}/gateway/mandates/draft`, { body }),
  signMandate: (id: string, body: StandingMandateRequest) =>
    request<MandateResult>("POST", `${biz(id)}/gateway/mandates`, { body }),

  // Audit
  audit: (q: { kind?: string; offset?: number; limit?: number } = {}) =>
    request<AuditPage>("GET", "/audit", { query: q }),
  auditHead: () => request<Head>("GET", "/audit/head"),
  auditVerify: () => request<VerifyResult>("GET", "/audit/verify"),

  // Simulated clock
  clock: () => request<ClockState>("GET", "/clock"),
  advanceClock: (body: AdvanceRequest) => request<ClockState>("POST", "/clock/advance", { body }),
};
