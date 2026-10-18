import * as React from 'react';

/**
 * Side drawer. Maps to shadcn/ui Sheet. Closes on Esc and scrim click. Primary use: the trace drawer that explains a FactNumber.
 */
export interface SheetProps {
  open: boolean;
  onOpenChange?: (open: boolean) => void;
  title?: React.ReactNode;
  description?: React.ReactNode;
  children?: React.ReactNode;
  /** Sticky bottom area for buttons. */
  footer?: React.ReactNode;
  side?: 'right' | 'left';
  /** Panel width in px. Default 440. */
  width?: number;
  /** Position absolutely inside the nearest positioned parent instead of the viewport (for previews and embedded panels). */
  contained?: boolean;
  className?: string;
}
export declare function Sheet(props: SheetProps): JSX.Element | null;
