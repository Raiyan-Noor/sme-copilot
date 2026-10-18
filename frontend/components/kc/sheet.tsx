"use client";

import { X } from "lucide-react";
import { useEffect } from "react";

import { cn } from "@/lib/utils";

/** Sheet (design/components/sheet): right-side drawer over a scrim, the only overlay in the app. Esc closes it. */
export function Sheet({
  open,
  onClose,
  title,
  description,
  children,
  footer,
  width = 480,
  className,
}: {
  open: boolean;
  onClose: () => void;
  title: React.ReactNode;
  description?: React.ReactNode;
  children: React.ReactNode;
  footer?: React.ReactNode;
  width?: number;
  className?: string;
}) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.stopPropagation();
        onClose();
      }
    };
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, [open, onClose]);

  if (!open) return null;
  return (
    <div className={cn("kc-sheet", className)}>
      <div className="kc-sheet__scrim" onClick={onClose} />
      <aside
        role="dialog"
        aria-modal="true"
        aria-label={typeof title === "string" ? title : undefined}
        className="kc-sheet__panel kc-sheet__panel--right"
        style={{ width }}
      >
        <header className="kc-sheet__head">
          <div className="kc-sheet__titles">
            <h2 className="kc-section-title">{title}</h2>
            {description ? <p className="kc-sheet__desc">{description}</p> : null}
          </div>
          <button type="button" className="kc-sheet__close" aria-label="Close" onClick={onClose}>
            <X size={20} strokeWidth={1.5} />
          </button>
        </header>
        <div className="kc-sheet__body">{children}</div>
        {footer ? <footer className="kc-sheet__foot">{footer}</footer> : null}
      </aside>
    </div>
  );
}
