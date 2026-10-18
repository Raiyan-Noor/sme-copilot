"use client";

import { useState } from "react";

import { useBusiness } from "@/components/business-context";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import { shortDate } from "@/lib/format";

import { useAdvisor } from "./state";

/**
 * Fast-forward the simulated clock to tomorrow morning: the backend moves the clock and runs the overnight job
 * (reminders through the gateway, then the Morning Brief) for every business. Every figure depends on the date, so
 * all data is refetched afterwards.
 */
export function useFastForward() {
  const { business, resetSession } = useBusiness();
  const { toast } = useAdvisor();
  const [busy, setBusy] = useState(false);

  const run = async () => {
    setBusy(true);
    try {
      const r = await api.advanceClock({ days: 1, run_overnight: true });
      const mine = r.overnight?.find((o) => o.business_id === business?.id);
      const sent = mine?.reminders.filter((x) => x.status === "executed").length ?? 0;
      toast({
        variant: "success",
        title: `Moved to ${shortDate(r.today)}, 7:00 am`,
        description: mine
          ? `Overnight checks ran. ${sent === 0 ? "No reminders" : sent === 1 ? "One reminder" : `${sent} reminders`} sent within your signed limits.`
          : "Overnight checks ran.",
      });
    } catch (e) {
      toast({ variant: "danger", title: "Could not fast-forward", description: errorMessage(e) });
    } finally {
      setBusy(false);
      resetSession();
    }
  };
  return { run, busy };
}
