import * as React from 'react';

/**
 * One chat message between the owner and the copilot.
 * @startingPoint section="Copilot" subtitle="Owner and copilot chat bubbles" viewport="700x300"
 */
export interface ChatBubbleProps {
  /** owner: right-aligned, quiet surface-raised bubble, sans. copilot: left-aligned, no bubble — the advisor speaks in the serif (--font-advisor) beside the mark. */
  role: 'owner' | 'copilot';
  /** Message body. FactNumbers inside copilot messages are encouraged. */
  children: React.ReactNode;
  /** Caption under the bubble, e.g. "9:14 am". */
  meta?: React.ReactNode;
  /** Optional sender name above the bubble. */
  name?: React.ReactNode;
  /** Copilot avatar image, usually assets/logo-mark.png. Falls back to a "K" monogram. */
  avatarSrc?: string;
  /** Rich content below the bubble, e.g. an ApprovalCard. */
  attachment?: React.ReactNode;
  className?: string;
}
export declare function ChatBubble(props: ChatBubbleProps): JSX.Element;
