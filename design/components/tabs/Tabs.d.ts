import * as React from 'react';

/**
 * Underline tab list. Maps to shadcn/ui Tabs. Controlled (value) or uncontrolled (defaultValue). Arrow keys move between tabs.
 */
export interface TabsProps {
  items: { value: string; label: React.ReactNode; count?: number }[];
  value?: string;
  defaultValue?: string;
  onValueChange?: (value: string) => void;
  /** sm 36px, md 44px. */
  size?: 'sm' | 'md';
  className?: string;
}
export declare function Tabs(props: TabsProps): JSX.Element;
