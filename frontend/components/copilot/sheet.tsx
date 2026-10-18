"use client";

import { X } from "lucide-react";
import { useEffect } from "react";

import { cn } from "@/lib/utils";

/** Right-side drawer with a scrim: the only overlay in the app (trace drawer, approval sheet). Esc closes it. */
export function Sheet({
  open,
  onClose,
  title,
  description,
  children,
  footer,
  className,
}: {
  open: boolean;
  onClose: () => void;
  title: React.ReactNode;
  description?: React.ReactNode;
  children: React.ReactNode;
  footer?: React.ReactNode;
  className?: string;
}) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50">
      <div className="absolute inset-0 animate-in bg-overlay-scrim fade-in-0" onClick={onClose} aria-hidden />
      <aside
        role="dialog"
        aria-modal="true"
        aria-label={typeof title === "string" ? title : undefined}
        className={cn(
          "absolute inset-y-0 right-0 flex w-full max-w-[480px] animate-in flex-col bg-surface-muted text-text shadow-float duration-300 fade-in-0 slide-in-from-right-6",
          className,
        )}
      >
        <header className="flex items-start justify-between gap-4 px-7 pt-7 pb-3">
          <div className="flex min-w-0 flex-col gap-1">
            <h2 className="text-[17px] leading-6 font-medium">{title}</h2>
            {description && <p className="text-[13px] leading-[18px] text-text-muted">{description}</p>}
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="-mt-0.5 -mr-1 rounded-sm p-1 text-text-muted hover:bg-surface-raised hover:text-text"
          >
            <X className="size-5" strokeWidth={1.5} />
          </button>
        </header>
        <div className="flex-1 overflow-y-auto px-7 pt-3 pb-7">{children}</div>
        {footer && <footer className="flex flex-wrap gap-2 px-7 pt-4 pb-6">{footer}</footer>}
      </aside>
    </div>
  );
}
