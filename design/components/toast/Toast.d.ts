import * as React from 'react';

/**
 * Transient confirmation after an action. Maps to shadcn/ui Toast (Sonner). Stateless — the host positions and dismisses it.
 */
export interface ToastProps {
  /** default (info icon), success (circle-check), danger (ban), savings (gold coins). */
  variant?: 'default' | 'success' | 'danger' | 'savings';
  /** Past tense, plain: "Payment scheduled". */
  title: React.ReactNode;
  description?: React.ReactNode;
  /** Single text action, usually "Undo" or "View". */
  action?: { label: string; onClick: () => void };
  onClose?: () => void;
  /** Override the variant icon (Lucide name). */
  icon?: string;
  className?: string;
}
export declare function Toast(props: ToastProps): JSX.Element;
