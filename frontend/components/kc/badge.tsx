import { Coins, type LucideIcon } from "lucide-react";

import { cn } from "@/lib/utils";

/** Badge (design/components/badge): neutral, brand, savings (green, coins icon), outline. */
export function Badge({
  variant = "neutral",
  icon,
  children,
  className,
}: {
  variant?: "neutral" | "brand" | "savings" | "outline";
  icon?: LucideIcon | null;
  children: React.ReactNode;
  className?: string;
}) {
  const Icon = icon === undefined && variant === "savings" ? Coins : icon;
  return (
    <span className={cn("kc-badge", `kc-badge--${variant}`, className)}>
      {Icon ? <Icon size={14} strokeWidth={1.5} aria-hidden /> : null}
      <span>{children}</span>
    </span>
  );
}
