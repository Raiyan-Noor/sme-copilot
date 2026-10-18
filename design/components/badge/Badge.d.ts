import * as React from 'react';

/**
 * Small rectangular label. Maps to shadcn/ui Badge.
 */
export interface BadgeProps {
  /** neutral: tags and counts. brand: KaChing-owned labels. savings: green, for money found or saved. outline: quiet metadata. */
  variant?: 'neutral' | 'brand' | 'savings' | 'outline';
  /** Lucide icon name. savings defaults to "coins"; pass null to hide. */
  icon?: string | null;
  children?: React.ReactNode;
  className?: string;
}
export declare function Badge(props: BadgeProps): JSX.Element;
