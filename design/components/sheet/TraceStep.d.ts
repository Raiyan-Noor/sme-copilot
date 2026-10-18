import * as React from 'react';

/** One line of a calculation trace inside a Sheet: operator, label, source, value. */
export interface TraceStepProps {
  label: React.ReactNode;
  value: React.ReactNode;
  /** Where the figure came from, e.g. "Chase checking ··4410, Oct 17". */
  source?: React.ReactNode;
  /** Operator shown in the gutter: "+", "−", "=". */
  op?: string;
  /** Bold total row with a rule above. */
  emphasis?: boolean;
}
export declare function TraceStep(props: TraceStepProps): JSX.Element;
