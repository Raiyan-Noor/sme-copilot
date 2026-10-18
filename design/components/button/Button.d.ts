import * as React from 'react';

/**
 * Action button. Maps to shadcn/ui Button. Labels are verb first, sentence case ("Sign and approve").
 * @startingPoint section="Actions" subtitle="Primary, secondary, ghost and destructive buttons" viewport="700x260"
 */
export interface ButtonProps extends Omit<React.ButtonHTMLAttributes<HTMLButtonElement>, 'type'> {
  /** primary: one per view, the main action. secondary: alternatives. ghost: low-emphasis, toolbars. destructive: block, decline, cancel payment. */
  variant?: 'primary' | 'secondary' | 'ghost' | 'destructive';
  /** sm 32px, md 40px, lg 48px. */
  size?: 'sm' | 'md' | 'lg';
  /** Lucide icon name before the label. */
  iconLeft?: string;
  /** Lucide icon name after the label. */
  iconRight?: string;
  loading?: boolean;
  disabled?: boolean;
  fullWidth?: boolean;
  type?: 'button' | 'submit' | 'reset';
  children?: React.ReactNode;
}
export declare function Button(props: ButtonProps): JSX.Element;
