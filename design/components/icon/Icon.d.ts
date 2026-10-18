import * as React from 'react';

/** Lucide icon wrapper. Always 1.5px stroke, inherits currentColor. */
export interface IconProps {
  /** Lucide icon name in kebab-case, e.g. "circle-check", "shield-alert", "coins". */
  name: string;
  /** Pixel size. 16 inline with labels, 20 default, 24 for empty states. */
  size?: 16 | 20 | 24 | number;
  /** Defaults to 1.5. Do not change in product UI. */
  strokeWidth?: number;
  color?: string;
  /** Accessible label. Omit for decorative icons next to text. */
  title?: string;
  className?: string;
  style?: React.CSSProperties;
}
export declare function Icon(props: IconProps): JSX.Element;
