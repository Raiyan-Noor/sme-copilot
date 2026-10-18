import * as React from 'react';

/**
 * One permission tier the owner has signed. Lists the mode, the money limit, and the tools the copilot may use.
 * @startingPoint section="Copilot" subtitle="Signed permission tiers with tools" viewport="700x320"
 */
export interface TierRowProps {
  /** Tier number shown in the circle. */
  tier: number | string;
  /** e.g. "Everyday upkeep", "Paying suppliers", "Moving money". */
  name: string;
  description?: React.ReactNode;
  /** auto = "Acts on its own", approval = "Asks first", never = "Never". */
  mode?: 'auto' | 'approval' | 'never';
  /** Formatted limit, e.g. "$500 per action". */
  limit?: React.ReactNode;
  /** Tool names or { label, icon } objects shown as chips. */
  tools?: (string | { label: string; icon?: string })[];
  /** e.g. "Signed by Maria Lopez, Sep 2". */
  signedNote?: React.ReactNode;
  onEdit?: () => void;
  editLabel?: string;
  className?: string;
}
export declare function TierRow(props: TierRowProps): JSX.Element;
