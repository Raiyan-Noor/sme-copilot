import type { Fact } from "@/lib/types";
import { cn } from "@/lib/utils";

import { FactNumber } from "./fact-number";

/** A big traceable figure with a label. Light weight, tabular, never bold. */
export function KpiTile({
  label,
  fact,
  caption,
  size = "lg",
  className,
}: {
  label: string;
  fact: Fact | null | undefined;
  caption?: React.ReactNode;
  size?: "lg" | "md";
  className?: string;
}) {
  return (
    <div className={cn("flex min-w-0 flex-col gap-2", className)}>
      <span className="text-[13px] leading-[18px] text-text-muted">{label}</span>
      <span
        className={cn(
          "font-light tracking-tight text-balance",
          size === "lg" ? "text-[40px] leading-[1.15] md:text-5xl" : "text-[28px] leading-[1.2]",
        )}
      >
        <FactNumber fact={fact} />
      </span>
      {caption && <span className="text-xs text-text-muted">{caption}</span>}
    </div>
  );
}
