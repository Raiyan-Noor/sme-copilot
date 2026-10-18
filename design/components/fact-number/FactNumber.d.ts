import * as React from 'react';

/**
 * Clickable figure with a subtle dotted underline. Clicking opens the trace drawer (Sheet) showing the source of the number.
 */
export interface FactNumberProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  /** The formatted figure, e.g. "$4,280". Inherits font size and weight from its parent. */
  children: React.ReactNode;
  /** Open the trace drawer. */
  onClick?: (e: React.MouseEvent<HTMLButtonElement>) => void;
  /** Short source description used in the tooltip and accessible label, e.g. "Bank feed, 3 accounts". */
  source?: string;
  /** default inherits text color; positive uses success; negative uses danger. */
  tone?: 'default' | 'positive' | 'negative';
}
export declare function FactNumber(props: FactNumberProps): JSX.Element;
