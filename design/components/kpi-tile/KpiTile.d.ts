import * as React from 'react';

/**
 * KPI tile: label, big tabular figure, optional delta and caption.
 * @startingPoint section="Data" subtitle="KPI tiles with traceable figures" viewport="700x200"
 */
export interface KpiTileProps {
  /** Sentence case, e.g. "Cash on hand". */
  label: string;
  /** Pre-formatted figure, e.g. "$18,240". */
  value: React.ReactNode;
  /** tone good = success green + trending-up, bad = danger + trending-down, neutral = muted. */
  delta?: { label: string; tone?: 'good' | 'bad' | 'neutral' };
  /** Muted line after the delta, e.g. "vs last month". */
  caption?: string;
  /** Lucide icon name before the label. */
  icon?: string;
  /** lg = 48px display number, md = 32px. */
  size?: 'md' | 'lg';
  /** When set, value renders as a FactNumber that calls this. */
  onTrace?: () => void;
  source?: string;
  className?: string;
}
export declare function KpiTile(props: KpiTileProps): JSX.Element;
