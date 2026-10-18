"use client";

import { createContext, useContext, useEffect, useState } from "react";

import { api } from "@/lib/api";
import type { BusinessInfo } from "@/lib/types";
import { useApi, type ApiState } from "@/lib/use-api";

const SELECTED_KEY = "business";

type BusinessContextValue = {
  businesses: ApiState<BusinessInfo[]>;
  business: BusinessInfo | undefined;
  select: (id: string) => void;
  /** Bumped when the passcode changes, so every page refetches. */
  session: number;
  resetSession: () => void;
};

const BusinessContext = createContext<BusinessContextValue | null>(null);

export function BusinessProvider({ children }: { children: React.ReactNode }) {
  const [session, setSession] = useState(0);
  const businesses = useApi(`businesses:${session}`, api.businesses);
  const [selected, setSelected] = useState<string | null>(null);

  useEffect(() => {
    try {
      const saved = localStorage.getItem(SELECTED_KEY);
      // Reading browser storage has to wait for the client; one extra render is fine here.
      // eslint-disable-next-line react-hooks/set-state-in-effect
      if (saved) setSelected(saved);
    } catch {
      // Storage blocked: fall back to the first business.
    }
  }, []);

  const list = businesses.data ?? [];
  const business = list.find((b) => b.id === selected) ?? list[0];

  const select = (id: string) => {
    setSelected(id);
    try {
      localStorage.setItem(SELECTED_KEY, id);
    } catch {
      // Not persisted; selection lasts for this page load.
    }
  };

  return (
    <BusinessContext.Provider
      value={{ businesses, business, select, session, resetSession: () => setSession((s) => s + 1) }}
    >
      {children}
    </BusinessContext.Provider>
  );
}

export function useBusiness(): BusinessContextValue {
  const ctx = useContext(BusinessContext);
  if (!ctx) throw new Error("useBusiness must be used inside <BusinessProvider>");
  return ctx;
}

/** A cache key for business-scoped fetches, or null until a business is known. */
export function useBusinessKey(name: string): { id: string; key: string | null } {
  const { business, session } = useBusiness();
  return { id: business?.id ?? "", key: business ? `${name}:${business.id}:${session}` : null };
}
