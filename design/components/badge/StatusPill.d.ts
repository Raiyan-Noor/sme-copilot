import * as React from 'react';

/**
 * Status pill for agent actions and offer fit. Always renders an icon plus a word.
 */
export interface StatusPillProps {
  /** executed (green), waiting = "Waiting for approval" (burnt orange), blocked (red), fits (green), doesnt-fit (neutral), synthetic = "Synthetic data" (dashed neutral). */
  status: 'executed' | 'waiting' | 'blocked' | 'fits' | 'doesnt-fit' | 'synthetic';
  /** Override the default word. Keep it short. */
  label?: string;
  size?: 'sm' | 'md';
  className?: string;
}
export declare function StatusPill(props: StatusPillProps): JSX.Element;
