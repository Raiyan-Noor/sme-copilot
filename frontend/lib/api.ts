/**
 * Typed client for the FastAPI backend. The browser calls NEXT_PUBLIC_API_URL directly (no Next rewrites).
 *
 * Every protected route needs the demo passcode in `X-Passcode`. The owner types it once; it is kept in this
 * browser's localStorage and never sent anywhere except the API.
 */
import type {
  AdvanceRequest,
  AnchorRequestResult,
  AnchorStatus,
  Answer,
  AuditVerifyResult,
  ConsoleInfo,
  Contacts,
  FinishResult,
  GmailConnectStart,
  GmailImportStarted,
  GmailPollResult,
  GmailStatus,
  InboxSourceChoice,
  InboxChoice,
  InboxRecord,
  NewBusiness,
  OnboardingView,
  ResetResult,
  SendResult,
  SkillPreview,
  Skip,
  StartingPoint,
  UploadResult,
  LeafCheck,
  PassportExportSummary,
  AdvanceResult,
  AskRequest,
  InboxDetail,
  InboxList,
  InboxSyncResult,
  FinancingResponse,
  LeakView,
  LimitsView,
  LoanApplicationRequest,
  LoanApplicationResponse,
  MorningBrief,
  PassportExport,
  PassportResponse,
  RedteamReport,
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
  TransactionRow,
  CallVerification,
  Payee,
  PayeeCreate,
  PaymentConnectionStatus,
  PaymentConnectRequest,
  PaymentConnectStart,
  PaymentCreate,
  PaymentView,
  PaymentsOverview,
  Receipt,
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

export type TransactionQuery = {
  date_from?: string;
  date_to?: string;
  category?: string;
  account_id?: string;
  search?: string;
  direction?: "in" | "out";
  order?: "asc" | "desc";
  offset?: number;
  limit?: number;
};

function authHeaders(): Record<string, string> {
  return { [PASSCODE_HEADER]: getPasscode() || memoryPasscode };
}

async function request<T>(method: string, path: string, opts: { query?: Query; body?: unknown } = {}): Promise<T> {
  const url = new URL(API_URL + path);
  for (const [k, v] of Object.entries(opts.query ?? {})) {
    if (v !== undefined && v !== null && v !== "") url.searchParams.set(k, String(v));
  }
  const headers = authHeaders();
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

  // Onboarding from zero
  skills: () => request<SkillPreview[]>("GET", "/skills"),
  previewSkill: (file: File) => {
    const form = new FormData();
    form.append("file", file, file.name);
    return request<SkillPreview>("POST", "/skills/preview", { body: form });
  },
  startOnboarding: (body: NewBusiness) => request<BusinessInfo>("POST", "/onboarding", { body }),
  resetOnboarding: () => request<ResetResult>("POST", "/onboarding/reset"),
  onboarding: (id: string) => request<OnboardingView>("GET", `${biz(id)}/onboarding`),
  setStartingPoint: (id: string, body: StartingPoint) =>
    request<OnboardingView>("PUT", `${biz(id)}/onboarding/starting-point`, { body }),
  answer: (id: string, body: Answer) => request<OnboardingView>("POST", `${biz(id)}/onboarding/answers`, { body }),
  skipNeed: (id: string, body: Skip) => request<OnboardingView>("POST", `${biz(id)}/onboarding/skip`, { body }),
  uploadOnboardingFile: (id: string, file: File) => {
    const form = new FormData();
    form.append("file", file, file.name);
    return request<UploadResult>("POST", `${biz(id)}/onboarding/uploads`, { body: form });
  },
  onboardingDocument: (id: string, emailId: string) =>
    request<InboxRecord>("GET", `${biz(id)}/onboarding/documents/${enc(emailId)}`),
  approveDocument: (id: string, emailId: string) =>
    request<Record<string, string>>("POST", `${biz(id)}/onboarding/documents/${enc(emailId)}/approve`),
  confirmContacts: (id: string, body: Contacts) =>
    request<OnboardingView>("POST", `${biz(id)}/onboarding/contacts`, { body }),
  setInbox: (id: string, body: InboxChoice) => request<OnboardingView>("PUT", `${biz(id)}/onboarding/inbox`, { body }),
  finishOnboarding: (id: string) => request<FinishResult>("POST", `${biz(id)}/onboarding/finish`),
  deleteBusiness: (id: string) => request<ResetResult>("DELETE", biz(id)),

  // Ledger
  transactions: (id: string, q: TransactionQuery = {}) =>
    request<TransactionPage>("GET", `${biz(id)}/transactions`, { query: q }),
  transaction: (id: string, rowId: string) =>
    request<TransactionRow>("GET", `${biz(id)}/transactions/${enc(rowId)}`),
  exportTransactions: async (id: string, q: TransactionQuery = {}): Promise<Blob> => {
    const url = new URL(API_URL + `${biz(id)}/transactions/export`);
    for (const [k, v] of Object.entries(q)) {
      if (v !== undefined && v !== null && v !== "") url.searchParams.set(k, String(v));
    }
    const res = await fetch(url, { headers: authHeaders(), cache: "no-store" });
    if (!res.ok) throw new ApiError(res.status, res.statusText);
    return res.blob();
  },
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
  leaks: (id: string) => request<LeakView[]>("GET", `${biz(id)}/leaks`),

  // Morning Brief
  brief: (id: string) => request<MorningBrief>("GET", `${biz(id)}/brief`),

  // Inbox (quarantined extractor + sentinel)
  inbox: (id: string) => request<InboxList>("GET", `${biz(id)}/inbox`),
  inboxItem: (id: string, emailId: string) => request<InboxDetail>("GET", `${biz(id)}/inbox/${enc(emailId)}`),
  // Demo console (only mounted when the server runs with DEMO_MODE)
  demoConsole: (id: string) => request<ConsoleInfo>("GET", `${biz(id)}/demo/console`),
  demoSendPreset: (id: string, preset: string) =>
    request<SendResult>("POST", `${biz(id)}/demo/send-preset`, { body: { preset } }),
  demoSendCustom: (id: string, form: FormData) =>
    request<SendResult>("POST", `${biz(id)}/demo/send-custom`, { body: form }),
  syncInbox: (id: string) => request<InboxSyncResult>("POST", `${biz(id)}/inbox/sync`),

  // Gmail connection (OAuth; the refresh token never leaves the server)
  gmailStatus: (id: string) => request<GmailStatus>("GET", `${biz(id)}/connections/gmail`),
  gmailConnect: (id: string) => request<GmailConnectStart>("POST", `${biz(id)}/connections/gmail/connect`),
  gmailDisconnect: (id: string) => request<GmailStatus>("POST", `${biz(id)}/connections/gmail/disconnect`),
  gmailSource: (id: string, body: InboxSourceChoice) =>
    request<GmailStatus>("PUT", `${biz(id)}/connections/gmail/source`, { body }),
  gmailPoll: (id: string) => request<GmailPollResult>("POST", `${biz(id)}/connections/gmail/poll`),
  gmailImportRecent: (id: string) => request<GmailImportStarted>("POST", `${biz(id)}/connections/gmail/import`),

  // Payments (SandboxPay, the simulated provider). Approving uses the gateway's approve route, signed here.
  payments: (id: string, q: { status?: PaymentView["status"]; payee_id?: string } = {}) =>
    request<PaymentsOverview>("GET", `${biz(id)}/payments`, { query: q }),
  createPayment: (id: string, body: PaymentCreate) =>
    request<PaymentView>("POST", `${biz(id)}/payments/requests`, { body }),
  payment: (id: string, rid: string) => request<PaymentView>("GET", `${biz(id)}/payments/requests/${enc(rid)}`),
  cancelPayment: (id: string, rid: string) =>
    request<PaymentView>("POST", `${biz(id)}/payments/requests/${enc(rid)}/cancel`),
  refreshPayment: (id: string, rid: string) =>
    request<PaymentView>("POST", `${biz(id)}/payments/requests/${enc(rid)}/refresh`),
  paymentReceipt: (id: string, rid: string) =>
    request<Receipt>("GET", `${biz(id)}/payments/requests/${enc(rid)}/receipt`),
  paymentOnchain: (id: string, rid: string) =>
    request<LeafCheck>("GET", `${biz(id)}/payments/requests/${enc(rid)}/onchain`),
  addPayee: (id: string, body: PayeeCreate) => request<Payee>("POST", `${biz(id)}/payments/payees`, { body }),
  verifyCall: (id: string, body: CallVerification) =>
    request<void>("POST", `${biz(id)}/payments/verifications`, { body }),
  paymentConnection: (id: string) => request<PaymentConnectionStatus>("GET", `${biz(id)}/connections/payments`),
  paymentConnect: (id: string, body: PaymentConnectRequest) =>
    request<PaymentConnectStart>("POST", `${biz(id)}/connections/payments/connect`, { body }),
  paymentDisconnect: (id: string) =>
    request<PaymentConnectionStatus>("POST", `${biz(id)}/connections/payments/disconnect`),

  // Financing and the Readiness Passport
  financing: (id: string) => request<FinancingResponse>("GET", `${biz(id)}/financing`),
  passport: (id: string) => request<PassportResponse>("GET", `${biz(id)}/passport`),
  exportPassport: (id: string) => request<PassportExport>("POST", `${biz(id)}/passport/export`),
  passportExports: (id: string) => request<PassportExportSummary[]>("GET", `${biz(id)}/passport/exports`),
  prepareApplication: (id: string, body: LoanApplicationRequest) =>
    request<LoanApplicationResponse>("POST", `${biz(id)}/financing/applications`, { body }),

  // Trust
  limits: (id: string) => request<LimitsView>("GET", `${biz(id)}/limits`),
  redteam: () => request<RedteamReport>("GET", "/redteam"),

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
  auditVerify: () => request<AuditVerifyResult>("GET", "/audit/verify"),

  // On-chain anchoring (hashes only, testnet only)
  anchors: () => request<AnchorStatus>("GET", "/anchors"),
  anchorNow: () => request<AnchorRequestResult>("POST", "/anchors"),
  mandateOnchain: (id: string, mandateId: number) =>
    request<LeafCheck>("GET", `${biz(id)}/gateway/mandates/${mandateId}/onchain`),
  passportOnchain: (id: string, sha256: string) =>
    request<LeafCheck>("GET", `${biz(id)}/passport/exports/${enc(sha256)}/onchain`),
  verifyPassportFile: (passport: Record<string, unknown>) =>
    request<LeafCheck>("POST", "/anchors/verify/passport", { body: passport }),

  // Simulated clock
  clock: () => request<ClockState>("GET", "/clock"),
  advanceClock: (body: AdvanceRequest) => request<AdvanceResult>("POST", "/clock/advance", { body }),
};

async function* sseFrames(res: Response): AsyncGenerator<{ event: string; data: unknown }> {
  if (!res.ok || !res.body) {
    const text = await res.text();
    let detail: unknown = res.statusText;
    try {
      detail = JSON.parse(text)?.detail ?? detail;
    } catch {
      // not JSON
    }
    throw new ApiError(res.status, detail);
  }
  const reader = res.body.pipeThrough(new TextDecoderStream()).getReader();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += value.replace(/\r\n/g, "\n");
    let cut;
    while ((cut = buffer.indexOf("\n\n")) >= 0) {
      const frame = buffer.slice(0, cut);
      buffer = buffer.slice(cut + 2);
      let event = "message";
      const data: string[] = [];
      for (const line of frame.split("\n")) {
        if (line.startsWith("event:")) event = line.slice(6).trim();
        else if (line.startsWith("data:")) data.push(line.slice(5).trimStart());
      }
      if (data.length) yield { event, data: JSON.parse(data.join("\n")) };
    }
  }
}

/**
 * Ask the planner and read its turn as server-sent events (POST, so not EventSource). Yields each event as the
 * backend emits it: conversation, tool_call, action, error, reply, then done. The reply arrives whole, after the
 * Numeric Firewall; it is never streamed token by token.
 */
export async function* chatStream(
  businessId: string,
  body: AskRequest,
  signal?: AbortSignal,
): AsyncGenerator<{ event: string; data: unknown }> {
  const res = await fetch(`${API_URL}${biz(businessId)}/agent/chat`, {
    method: "POST",
    headers: { ...authHeaders(), "Content-Type": "application/json", Accept: "text/event-stream" },
    body: JSON.stringify(body),
    cache: "no-store",
    signal,
  });
  yield* sseFrames(res);
}

/**
 * New ledger rows as they're ingested, polled server-side from the same ledger version the engine caches on
 * (GET, so a plain fetch-and-read works like EventSource would, but with the passcode header EventSource can't
 * send). Yields `transaction` (one new row) and `balance` (the new running total) events.
 */
export async function* transactionStream(
  businessId: string,
  signal?: AbortSignal,
): AsyncGenerator<{ event: string; data: unknown }> {
  const res = await fetch(`${API_URL}${biz(businessId)}/transactions/stream`, {
    headers: { ...authHeaders(), Accept: "text/event-stream" },
    cache: "no-store",
    signal,
  });
  yield* sseFrames(res);
}

/** One live inbox event (GET /inbox/stream). Mirrors app/services/inbox_events.py `InboxEvent`. */
export interface PaymentStreamEvent {
  request_id: string;
  status: PaymentView["status"];
  payee_name: string;
  amount_minor: number;
  currency: string;
  rule: string | null;
}

export interface InboxStreamEvent {
  seq: number;
  kind: "message" | "connection" | "payment" | "payment_connection";
  email_id: string | null;
  source: string | null;
  stage: "received" | "extracting" | "checking" | "accepted" | "flagged" | "held" | "failed" | null;
  sender: string | null;
  subject: string | null;
  flags: string[];
  connection: GmailStatus | null;
  payment: PaymentStreamEvent | null;
}

/**
 * Each email's progress through quarantine and the sentinel (from Gmail, the sandbox mailbox or an upload), changes
 * to the Gmail connection, and each payment's status, as they happen. Yields `message`, `connection`, `payment` and
 * `payment_connection` events.
 */
export async function* inboxStream(
  businessId: string,
  signal?: AbortSignal,
): AsyncGenerator<{ event: string; data: InboxStreamEvent }> {
  const res = await fetch(`${API_URL}${biz(businessId)}/inbox/stream`, {
    headers: { ...authHeaders(), Accept: "text/event-stream" },
    cache: "no-store",
    signal,
  });
  for await (const frame of sseFrames(res)) yield frame as { event: string; data: InboxStreamEvent };
}
