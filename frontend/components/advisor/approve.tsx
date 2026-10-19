"use client";

import { api } from "@/lib/api";
import { money, ruleLabel } from "@/lib/format";
import type { PaymentView } from "@/lib/types";

import type { ApprovalOpen } from "./state";
import type { ToastData } from "@/components/kc/misc";

/**
 * Starting a payment: the one path the Payments tab and the Morning brief tab share. The server prepares the
 * payment and proposes it to the gateway (pay_invoice, T3, or a T2 bill under a signed limit); the result is the
 * gateway's decision. A payment that waits for the owner opens the same approval sheet the Outbox uses, where the
 * owner signs in the browser (invariants 1 and 6). Nothing here approves or signs anything itself.
 */
export type PaymentHandlers = {
  openApproval: (a: ApprovalOpen) => void;
  addPending: (ids: string[]) => void;
  toast: (t: ToastData) => void;
};

export function paymentContext(p: PaymentView) {
  return (
    <>
      Pay <strong>{p.payee_name}</strong> {money(p.amount_minor, p.currency)}
      {p.account_last4 ? ` to the account ending ${p.account_last4} (from your own records)` : ""}. {p.source_label}.
      Your signature covers the payee, the amount and that account: if any of them changes, it will not be paid.
    </>
  );
}

/** What happens after the gateway decides on a payment: sign it, report it sent, or report the refusal. */
export function followPayment(p: PaymentView, h: PaymentHandlers) {
  if (p.status === "awaiting_approval" && p.approval_id) {
    h.addPending([p.approval_id]);
    h.openApproval({ approvalId: p.approval_id, context: paymentContext(p) });
  } else if (p.status === "sent") {
    h.toast({ variant: "success", title: `Sent: ${p.payee_name}`, description: "Within your signed limit. Settling now." });
  } else if (p.status === "failed" || p.status === "denied") {
    h.toast({ variant: "danger", title: `Not paid: ${p.payee_name}`, description: p.rule ? ruleLabel(p.rule) : undefined });
  }
}

/** Prepare a suggested payment (`source` is its key) and follow the gateway's decision. */
export async function startPayment(businessId: string, source: string, h: PaymentHandlers): Promise<PaymentView> {
  const p = await api.createPayment(businessId, { source });
  followPayment(p, h);
  return p;
}
