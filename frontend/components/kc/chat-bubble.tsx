import { Logo } from "@/components/brand/Logo";
import { cn } from "@/lib/utils";

/** ChatBubble (design/components/chat-bubble): owner in a raised sans bubble, the advisor unboxed in serif. */
export function ChatBubble({
  role = "copilot",
  children,
  meta,
  name,
  attachment,
  className,
}: {
  role?: "copilot" | "owner";
  children?: React.ReactNode;
  meta?: React.ReactNode;
  name?: React.ReactNode;
  attachment?: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("kc-chat", `kc-chat--${role}`, className)}>
      {role === "copilot" ? (
        <div className="kc-chat__avatar" aria-hidden="true">
          <Logo variant="mark" />
        </div>
      ) : null}
      <div className="kc-chat__col">
        {name ? <div className="kc-chat__name">{name}</div> : null}
        {children ? <div className="kc-chat__bubble">{children}</div> : null}
        {attachment ? <div className="kc-chat__attach">{attachment}</div> : null}
        {meta ? <div className="kc-chat__meta">{meta}</div> : null}
      </div>
    </div>
  );
}
