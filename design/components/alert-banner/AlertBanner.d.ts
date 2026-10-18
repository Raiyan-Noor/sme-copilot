import * as React from 'react';

/**
 * Full-width banner for fraud warnings and neutral notices. Maps to shadcn/ui Alert.
 */
export interface AlertBannerProps {
  /** fraud: red, shield-alert icon, role="alert" — only for suspected fraud. info: neutral, info icon. */
  variant?: 'fraud' | 'info';
  /** Small word above the title. Defaults to "Possible fraud" / "Note". Pass null to hide. */
  eyebrow?: React.ReactNode;
  title?: React.ReactNode;
  children?: React.ReactNode;
  /** Buttons, e.g. destructive "Block payment" + secondary "It's legitimate". */
  actions?: React.ReactNode;
  onDismiss?: () => void;
  className?: string;
}
export declare function AlertBanner(props: AlertBannerProps): JSX.Element;
