import { APP_NAME } from "@/config/app";
import { cn } from "@/lib/utils";

/**
 * BRANDING 3/3: the only component that renders the logo. Placeholder: the app name as text.
 * When the logo asset arrives it lives in this folder and only this component imports it.
 */
export function Logo({ className }: { className?: string }) {
  return (
    <span className={cn("font-semibold tracking-tight text-brand-primary", className)} aria-label={APP_NAME}>
      {APP_NAME}
    </span>
  );
}
