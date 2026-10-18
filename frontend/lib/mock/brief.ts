/**
 * Morning Brief: the shape the Today screen renders, and preview data until the brief endpoint lands (build
 * prompt 14). Built from the API types: approvals are `ApprovalView`s, every figure is a `Fact`, and prose carries
 * `{fact:id}` placeholders instead of digits (invariant 4). Preview figures are labelled as such on screen; none of
 * them is a computed result.
 */
import type { ApprovalView, Decision, Fact } from "@/lib/types";

/** An action the copilot prepared, with what the owner needs to judge it. */
export interface PreparedAction {
  approval: ApprovalView;
  title: string;
  /** Plain sentence; may contain {fact:id} placeholders resolved from `facts`. */
  summary: string;
  amount: Fact | null;
  payee: string | null;
  details: { label: string; fact: Fact }[];
  /** Which signed limit or tier rule this falls under; may contain {fact:id}. */
  limit_note: string;
  risk_flags: string[];
  /** Set for first-time payees: the date signing opens. */
  cooling_off_until: Fact | null;
  facts: Record<string, Fact>;
}

export interface BriefAlert {
  id: string;
  kind: "fraud";
  title: string;
  /** Written by the sentinel in code, never by the extractor; may contain {fact:id}. */
  body: string;
  risk_flags: string[];
  facts: Record<string, Fact>;
}

export interface DoneItem {
  audit_seq: number;
  tool: string;
  summary: string;
  status: Decision["status"];
  date: Fact;
}

export interface ComingUpItem {
  id: string;
  label: string;
  amount: Fact;
  due: Fact;
}

export interface ImproveItem {
  leak_id: string;
  title: string;
  /** May contain {fact:id}. */
  text: string;
  yearly_saving: Fact;
  facts: Record<string, Fact>;
  action: PreparedAction | null;
}

export interface MorningBrief {
  business_id: string;
  as_of: Fact;
  /** True for preview data; the real endpoint returns false. */
  preview: boolean;
  /** Paragraphs with {fact:id} placeholders. */
  paragraphs: string[];
  facts: Record<string, Fact>;
  alerts: BriefAlert[];
  needs_you: PreparedAction[];
  done_overnight: DoneItem[];
  coming_up: ComingUpItem[];
  improve: ImproveItem | null;
}

const PREVIEW = "preview";

function fact(id: string, unit: Fact["unit"], value: Fact["value"], display: string): Fact {
  return { id, unit, value, display, source_row_ids: [], computed_by: PREVIEW, currency: unit === "money" ? "USD" : null };
}

const f = {
  asOf: fact("clock.today", "date", "2026-10-19", "Oct 19"),
  safeSpend: fact("brief.safe_to_spend_7d", "money", 428000, "$4,280"),
  safeUntil: fact("brief.safe_to_spend_until", "date", "2026-10-26", "Oct 26"),
  ggwAmount: fact("payable.MCS-SCH-0007.amount", "money", 309237, "$3,092.37"),
  ggwDue: fact("payable.MCS-SCH-0007.due", "date", "2026-10-21", "Oct 21"),
  ggwNewDue: fact("action.delay.new_due", "date", "2026-10-28", "Oct 28"),
  ggwLowPoint: fact("forecast.min_balance_if_paid", "money", 61200, "$612"),
  freshAmount: fact("payable.MCS-SCH-0008.amount", "money", 176987, "$1,769.87"),
  freshDue: fact("payable.MCS-SCH-0008.due", "date", "2026-10-23", "Oct 23"),
  posAmount: fact("payable.MCS-SCH-0004.amount", "money", 5900, "$59.00"),
  posDue: fact("payable.MCS-SCH-0004.due", "date", "2026-10-19", "Oct 19"),
  payroll: fact("payable.MCS-SCH-0011.amount", "money", 390000, "$3,900.00"),
  payrollDue: fact("payable.MCS-SCH-0011.due", "date", "2026-10-28", "Oct 28"),
  reminderAmount: fact("receivable.MCS-SCH-0003.amount", "money", 21400, "$214.00"),
  doneDate: fact("clock.yesterday", "date", "2026-10-18", "Oct 18"),
  leakMonthly: fact("leak.duplicate_subscription.monthly", "money", 5900, "$59"),
  leakYearly: fact("leak.duplicate_subscription.yearly", "money", 70800, "$708"),
};

const delayApproval: ApprovalView = {
  approval_id: "apr_preview_delay_ggw",
  tool: "delay_supplier_payment",
  status: "pending_approval",
  args: { payee_id: "sup_ggw", scheduled_item_id: "MCS-SCH-0007", new_due_date: "2026-10-28" },
  reasons: ["T3: delay_supplier_payment needs your signature on the exact payload"],
  payload: {
    action: "delay_supplier_payment",
    args_hash: "preview-not-a-real-hash",
    nonce: "preview-nonce",
    expiry: "2026-10-21",
  },
  message: "",
  requires_out_of_band_call_script: false,
};

const cancelApproval: ApprovalView = {
  approval_id: "apr_preview_cancel_pos",
  tool: "cancel_subscription",
  status: "pending_approval",
  args: { payee_id: "pay_shelfpos", subscription: "bill_pos_b" },
  reasons: ["T3: cancel_subscription needs your signature on the exact payload"],
  payload: {
    action: "cancel_subscription",
    args_hash: "preview-not-a-real-hash",
    nonce: "preview-nonce",
    expiry: "2026-10-21",
  },
  message: "",
  requires_out_of_band_call_script: false,
};

export const PREVIEW_BRIEFS: Record<string, MorningBrief> = {
  "maya-corner-store": {
    business_id: "maya-corner-store",
    as_of: f.asOf,
    preview: true,
    paragraphs: [
      "Morning, Maya. One payment needs your signature and one email looks wrong. Everything else is handled.",
      "Through {fact:brief.safe_to_spend_until} you can safely spend {fact:brief.safe_to_spend_7d} after the bills already scheduled.",
    ],
    facts: { [f.safeSpend.id]: f.safeSpend, [f.safeUntil.id]: f.safeUntil },
    alerts: [
      {
        id: "alert_preview_fresh_bank_change",
        kind: "fraud",
        title: "FreshLine Produce & Dairy's bank details changed",
        body:
          "An email asks you to pay invoice {fact:payable.MCS-SCH-0008.amount} to a new account. Their past invoices " +
          "all used the account on file. I paused the payment until you check with them by phone.",
        risk_flags: ["Bank details changed", "Lookalike domain", "Urgent wording"],
        facts: { [f.freshAmount.id]: f.freshAmount },
      },
    ],
    needs_you: [
      {
        approval: delayApproval,
        title: "Move the Golden Grain payment back a week",
        summary:
          "Paying {fact:payable.MCS-SCH-0007.amount} on {fact:payable.MCS-SCH-0007.due} takes your balance down to " +
          "{fact:forecast.min_balance_if_paid} before holiday sales come in. Their terms allow paying on " +
          "{fact:action.delay.new_due}.",
        amount: f.ggwAmount,
        payee: "Golden Grain Wholesale",
        details: [
          { label: "Due now", fact: f.ggwDue },
          { label: "New date", fact: f.ggwNewDue },
          { label: "Lowest balance if paid now", fact: f.ggwLowPoint },
        ],
        limit_note: "Tier 3: you sign this exact change",
        risk_flags: [],
        cooling_off_until: null,
        facts: {
          [f.ggwAmount.id]: f.ggwAmount,
          [f.ggwDue.id]: f.ggwDue,
          [f.ggwNewDue.id]: f.ggwNewDue,
          [f.ggwLowPoint.id]: f.ggwLowPoint,
        },
      },
    ],
    done_overnight: [
      {
        audit_seq: 0,
        tool: "send_invoice_reminder",
        summary: "Sent Greenleaf Cafe a reminder for their overdue invoice",
        status: "executed",
        date: f.doneDate,
      },
      {
        audit_seq: 0,
        tool: "pay_recurring_bill",
        summary: "Paid the internet bill to a known payee",
        status: "executed",
        date: f.doneDate,
      },
      {
        audit_seq: 0,
        tool: "pay_recurring_bill",
        summary: "Held a bill payment to a payee not on your signed list",
        status: "denied",
        date: f.doneDate,
      },
    ],
    coming_up: [
      { id: "MCS-SCH-0004", label: "Shelf POS subscription", amount: f.posAmount, due: f.posDue },
      { id: "MCS-SCH-0008", label: "FreshLine Produce & Dairy (paused)", amount: f.freshAmount, due: f.freshDue },
      { id: "MCS-SCH-0011", label: "Payroll", amount: f.payroll, due: f.payrollDue },
    ],
    improve: {
      leak_id: "duplicate_subscription",
      title: "Cancel the second point-of-sale plan",
      text: "You pay two point-of-sale plans. Only one has processed a sale since August. Cancelling the other saves {fact:leak.duplicate_subscription.monthly} a month.",
      yearly_saving: f.leakYearly,
      facts: { [f.leakMonthly.id]: f.leakMonthly, [f.leakYearly.id]: f.leakYearly },
      action: {
        approval: cancelApproval,
        title: "Cancel the second point-of-sale plan",
        summary: "Stops the {fact:leak.duplicate_subscription.monthly} monthly charge from Shelf POS.",
        amount: f.leakMonthly,
        payee: "Shelf POS",
        details: [{ label: "Saves a year", fact: f.leakYearly }],
        limit_note: "Tier 3: you sign this exact cancellation",
        risk_flags: [],
        cooling_off_until: null,
        facts: { [f.leakMonthly.id]: f.leakMonthly, [f.leakYearly.id]: f.leakYearly },
      },
    },
  },
};
