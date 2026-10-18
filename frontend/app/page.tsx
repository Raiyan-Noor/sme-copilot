"use client";

import { useBusiness, useBusinessKey } from "@/components/business-context";
import { FactTraceProvider } from "@/components/copilot/fact-number";
import { KpiTile } from "@/components/copilot/kpi-tile";
import { MorningBriefMessage } from "@/components/copilot/morning-brief";
import { Load } from "@/components/data";
import { api } from "@/lib/api";
import { PREVIEW_BRIEFS } from "@/lib/mock/brief";
import { useApi } from "@/lib/use-api";

/**
 * Today: real cash figures from GET /businesses/{id}/cash, then the Morning Brief. The brief is preview data
 * shaped like the API until its endpoint lands (build prompt 14), and is labelled as such.
 */
export default function TodayPage() {
  const { business } = useBusiness();
  const { id, key } = useBusinessKey("cash");
  const cash = useApi(key, () => api.cash(id));
  const brief = business ? PREVIEW_BRIEFS[business.id] : undefined;

  return (
    <FactTraceProvider>
      <div className="mx-auto flex w-full max-w-[720px] flex-col gap-10 pb-16">
        <h1 className="sr-only">Today</h1>
        <Load state={cash}>
          {(c) => (
            <div className="flex flex-col gap-6">
              <KpiTile label="Cash balance" fact={c.balance} />
              <div className="grid grid-cols-1 gap-6 sm:grid-cols-2">
                <KpiTile label="Runway" fact={c.runway_days} size="md" />
                <KpiTile label="Cash runs short on" fact={c.runway_date} size="md" />
              </div>
            </div>
          )}
        </Load>
        {brief ? (
          <MorningBriefMessage brief={brief} />
        ) : (
          <p className="font-advisor text-[19px] leading-[30px] text-text-muted">
            No morning brief for this business yet.
          </p>
        )}
      </div>
    </FactTraceProvider>
  );
}
