import Image from "next/image";

import { APP_NAME } from "@/config/app";
import { cn } from "@/lib/utils";

import mark from "./logo-mark.png";
import wordmark from "./logo-wordmark.png";

/**
 * BRANDING 3/3: the only component that renders the logo, and the only importer of the logo assets in this folder.
 * `wordmark` (default) is the dark-surface lockup for the top-left of the window; `mark` is the coin and arrow for
 * small spaces such as the advisor avatar. Size it with a height class; the width follows the aspect ratio.
 */
export function Logo({ variant = "wordmark", className }: { variant?: "wordmark" | "mark"; className?: string }) {
  const src = variant === "mark" ? mark : wordmark;
  return <Image src={src} alt={APP_NAME} priority className={cn("h-7 w-auto select-none", className)} />;
}
