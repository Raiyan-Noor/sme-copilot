import * as React from 'react';

/**
 * A prepared action waiting for the owner's signature: what, how much, why, and the signed limit it falls under.
 * @startingPoint section="Copilot" subtitle="Approval card with facts, limit note and sign button" viewport="700x340"
 */
export interface ApprovalCardProps {
  /** Verb-first summary, e.g. "Pay Fresh Farms invoice #2291". */
  title: React.ReactNode;
  /** Formatted amount, e.g. "$1,240.00". */
  amount?: React.ReactNode;
  /** Makes the amount a FactNumber that opens the trace. */
  onAmountClick?: () => void;
  /** One or two plain sentences on why. */
  description?: React.ReactNode;
  /** Short label/value pairs: Due, Account, Matched PO. */
  facts?: { label: string; value: React.ReactNode }[];
  /** Which signed limit applies, e.g. "Within your $2,000 'Ask first' limit". */
  limitNote?: React.ReactNode;
  /** waiting shows Sign/Decline buttons; executed and blocked show resolvedNote instead. */
  status?: 'waiting' | 'executed' | 'blocked';
  /** Top-right caption, e.g. "Prepared 9:14 am". */
  meta?: React.ReactNode;
  /** Shown when not waiting, e.g. "Signed by you at 10:42 am". */
  resolvedNote?: React.ReactNode;
  approveLabel?: string;
  declineLabel?: string;
  onApprove?: () => void;
  onDecline?: () => void;
  className?: string;
}
export declare function ApprovalCard(props: ApprovalCardProps): JSX.Element;
