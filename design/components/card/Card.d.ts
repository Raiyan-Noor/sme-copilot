import * as React from 'react';

/**
 * Surface container. Maps to shadcn/ui Card.
 * @startingPoint section="Layout" subtitle="Default, muted and 'one thing to improve' cards" viewport="700x300"
 */
export interface CardProps extends Omit<React.HTMLAttributes<HTMLElement>, 'title'> {
  /** default: surface-muted step, no border or shadow. muted: transparent group, spacing only. improve: thin gold outline "One thing to improve" card — max one per page. */
  variant?: 'default' | 'muted' | 'improve';
  /** Small label above the title. improve defaults to "One thing to improve". */
  eyebrow?: React.ReactNode;
  title?: React.ReactNode;
  description?: React.ReactNode;
  /** Top-right slot, usually a ghost Button or Badge. */
  action?: React.ReactNode;
  /** Bottom slot separated by a hairline; usually buttons. */
  footer?: React.ReactNode;
  /** sm 16px, md 20px, lg 24px. */
  padding?: 'sm' | 'md' | 'lg';
  children?: React.ReactNode;
}
export declare function Card(props: CardProps): JSX.Element;
