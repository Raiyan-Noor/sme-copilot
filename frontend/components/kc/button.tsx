import { LoaderCircle, type LucideIcon } from "lucide-react";

import { cn } from "@/lib/utils";

/** Design-system Button (design/components/button): primary, secondary, ghost, destructive; sm/md/lg. */
export function Button({
  variant = "primary",
  size = "md",
  iconLeft: IconLeft,
  iconRight: IconRight,
  loading = false,
  disabled = false,
  fullWidth = false,
  type = "button",
  className,
  children,
  ...rest
}: {
  variant?: "primary" | "secondary" | "ghost" | "destructive";
  size?: "sm" | "md" | "lg";
  iconLeft?: LucideIcon;
  iconRight?: LucideIcon;
  loading?: boolean;
  fullWidth?: boolean;
} & React.ButtonHTMLAttributes<HTMLButtonElement>) {
  const iconSize = size === "sm" ? 16 : 18;
  const hasText = children !== undefined && children !== null && children !== "";
  return (
    <button
      type={type}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      className={cn(
        "kc-btn",
        `kc-btn--${variant}`,
        `kc-btn--${size}`,
        fullWidth && "kc-btn--full",
        !hasText && "kc-btn--icon",
        className,
      )}
      {...rest}
    >
      {loading ? (
        <LoaderCircle size={iconSize} strokeWidth={1.5} className="kc-btn__spin" aria-hidden />
      ) : IconLeft ? (
        <IconLeft size={iconSize} strokeWidth={1.5} aria-hidden />
      ) : null}
      {hasText ? <span>{children}</span> : null}
      {IconRight && !loading ? <IconRight size={iconSize} strokeWidth={1.5} aria-hidden /> : null}
    </button>
  );
}
