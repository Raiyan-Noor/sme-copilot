import * as React from 'react';

/** Plain progress bar. Maps to shadcn/ui Progress. */
export interface ProgressProps {
  value: number;
  max?: number;
  /** brand green (default), teal (chart highlight), gold (savings), danger, neutral. */
  tone?: 'brand' | 'teal' | 'gold' | 'danger' | 'neutral';
  /** sm 6px, md 8px. */
  size?: 'sm' | 'md';
  /** Accessible label. */
  label?: string;
  className?: string;
}
export declare function Progress(props: ProgressProps): JSX.Element;
