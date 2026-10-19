/**
 * Owner-facing words for codes the backend returns (tools, rules, flags, fact IDs). Formatting only: figures the
 * owner sees come from Facts; the helpers below never compute a value.
 */
import type { Flag } from "@/lib/types";

const TOOL_TITLES: Record<string, string> = {
  send_invoice_reminder: "Send an invoice reminder",
  pay_recurring_bill: "Pay a recurring bill",
  submit_loan_application: "Send a loan application",
  change_payee_details: "Change a payee's bank details",
  delay_supplier_payment: "Delay a supplier payment",
  send_supplier_message: "Message a supplier",
  cancel_subscription: "Cancel a subscription",
  pay_invoice: "Pay an invoice",
};

const TOOL_SHORT: Record<string, string> = {
  send_invoice_reminder: "Invoice reminders",
  pay_recurring_bill: "Recurring bills",
  submit_loan_application: "Loan applications",
  change_payee_details: "Payee bank details",
  delay_supplier_payment: "Delay a supplier payment",
  send_supplier_message: "Supplier messages",
  cancel_subscription: "Cancel subscriptions",
  pay_invoice: "One-off payments",
};

const T1_SHORT: Record<string, string> = {
  "get_*": "Read your accounts",
  "list_*": "List records",
  explain_fact: "Explain any figure",
  match_financing: "Compare financing",
  get_passport: "Readiness Passport",
};

const T4_SHORT: Record<string, string> = {
  large_debt: "Take on large debt",
  hiring_or_firing: "Hire or fire staff",
  pricing_change: "Change prices",
  deal_commitment: "Commit to deals",
};

const FLAG_LABELS: Record<Flag["code"], string> = {
  lookalike_domain: "Lookalike domain",
  display_name_spoof: "Sender name doesn't match the address",
  reply_to_mismatch: "Replies go to a different address",
  bank_detail_change: "New bank account",
  first_time_payee: "First payment to this payee",
  amount_anomaly: "Unusual amount",
  urgency: "Pressure to pay quickly",
  instruction_like_text: "Instructions to the assistant",
  hidden_text: "Hidden text in the message",
  receipt_total_mismatch: "Receipt total doesn't add up",
  duplicate_invoice: "Possible duplicate invoice",
  amount_mismatch: "Amount doesn't match",
};

const RULE_LABELS: Record<string, string> = {
  no_standing_mandate: "No signed limit covers this yet",
  unknown_tool: "Not something the assistant is allowed to do",
  system_tool: "Only the system may do this",
  t1_is_not_an_action: "Read-only tools cannot act",
  bad_signature: "The signature did not match",
  replayed_nonce: "This approval was already used",
  expired: "The approval expired",
  args_hash_mismatch: "The details changed after they were prepared",
  approval_not_pending: "This approval was already decided",
  unknown_approval: "No such approval",
  unknown_signer: "This browser's key is not the owner's key",
  out_of_band_call_required: "Confirm you called them on a number you already had",
  over_mandate_cap: "Above the limit you signed",
  over_policy_cap: "Above the hard cap",
  frequency_cap: "Too soon after the last one",
  raises_policy_cap: "A limit may lower the hard cap, never raise it",
  mandate_too_long: "A standing limit cannot last that long",
  untrusted_source: "The due date came from an email, so it was not sent automatically",
  payee_account_changed: "The payee's bank account changed since you were asked, so it was not paid",
  call_script_verification_required: "Call the payee on a number you already had before paying this",
  payment_request_mismatch: "The payment details changed after they were prepared",
  payment_request_cancelled: "This payment was cancelled",
  unknown_payment_request: "No such payment request",
  not_connected: "No payment service is connected",
  no_account_on_file: "No bank account on file for this payee",
  unreachable: "The payment service could not be reached",
  over_per_payment_cap: "Above the per-payment limit you approved at the payment service",
  over_daily_cap: "Above the daily limit you approved at the payment service",
  token_revoked: "The payment service connection was revoked",
  account_closed: "The payee's bank refused it (account closed)",
};

export const sentence = (code: string) => {
  const s = code.replace(/[._]+/g, " ").trim();
  return s.charAt(0).toUpperCase() + s.slice(1);
};

export const toolTitle = (tool: string) => TOOL_TITLES[tool] ?? sentence(tool);
export const toolShort = (tool: string) => TOOL_SHORT[tool] ?? T1_SHORT[tool] ?? T4_SHORT[tool] ?? sentence(tool);
export const flagLabel = (code: Flag["code"]) => FLAG_LABELS[code] ?? sentence(code);
export const ruleLabel = (rule: string) => RULE_LABELS[rule] ?? sentence(rule);

/** Why an approval needs the owner, from the gateway's reason codes. */
export function reasonLabel(reason: string): string {
  if (reason === "tier_T3") return "This kind of action always waits for your signature.";
  if (reason.startsWith("untrusted_provenance:")) {
    const args = reason.slice("untrusted_provenance:".length).split(",").map(sentence).join(", ");
    return `Some values came from an email or upload (${args.toLowerCase()}), so it needs your signature.`;
  }
  return sentence(reason);
}

/** A fact ID as a label, for trace rows: "forecast.30d.min_balance" -> "Forecast 30d min balance". */
export const factLabel = (id: string) => sentence(id);

/** An ISO date (simulated clock) as "Oct 18". */
export function shortDate(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(`${iso.slice(0, 10)}T00:00:00Z`);
  return Number.isNaN(d.getTime())
    ? iso
    : d.toLocaleDateString("en-US", { month: "short", day: "numeric", timeZone: "UTC" });
}

/** Minor units as money, for the exact payload the owner signs and for policy caps (configuration, not facts). */
export function money(minor: number, currency: string | null | undefined): string {
  return new Intl.NumberFormat("en-US", { style: "currency", currency: currency || "USD" }).format(minor / 100);
}

export const nowTime = () =>
  new Date().toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" }).toLowerCase();
