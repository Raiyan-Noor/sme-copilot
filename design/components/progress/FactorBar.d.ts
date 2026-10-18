import * as React from 'react';

/**
 * Labelled factor bar: one factor of a decision (offer fit, limit used, fraud risk) with value, track and optional threshold tick.
 */
export interface FactorBarProps {
  label: string;
  value: number;
  max?: number;
  /** Formatted value on the right, e.g. "$1,240 of $2,000". Defaults to value. */
  valueLabel?: React.ReactNode;
  /** Muted explanation under the bar. */
  hint?: React.ReactNode;
  tone?: 'brand' | 'teal' | 'gold' | 'danger' | 'neutral';
  /** Position of a vertical tick (same units as value), e.g. a signed limit. */
  threshold?: number;
  thresholdLabel?: string;
  className?: string;
}
export declare function FactorBar(props: FactorBarProps): JSX.Element;
