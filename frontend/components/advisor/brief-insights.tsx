"use client";

import { Lightbulb } from "lucide-react";

import { Card } from "@/components/kc/card";
import { FactNumber } from "@/components/kc/fact";
import type { MorningBrief, ProductLine } from "@/lib/types";

/**
 * Product and ad insights under the brief's prose: best and worst margins, stock about to run out, stock that is
 * not selling, campaigns that cost more than they bring in and the channel with the best return. Every figure is
 * an engine Fact (invariant 4). Hidden when the business has no product or ad data.
 */
export function BriefInsights({ brief }: { brief: MorningBrief }) {
  const p = brief.products;
  const ads = brief.ads;
  if (!p && !ads) return null;
  return (
    <Card padding="md" eyebrow="Products and ads" title="What your products and ads are doing">
      <ul className="ka-foldlist ka-insights">
        {p?.best_margin ? <Row label="Best margin" line={p.best_margin} metric="margin" /> : null}
        {p?.worst_margin ? <Row label="Weakest margin" line={p.worst_margin} metric="margin" /> : null}
        {p?.stockout_risk?.map((l) => (
          <Row key={l.product_id} label="About to run out" line={l} metric="cover" />
        ))}
        {p?.slow_movers?.map((l) => (
          <Row key={l.product_id} label="Not selling" line={l} metric="cover" />
        ))}
        {ads?.losing?.map((c) => (
          <li key={c.campaign_id}>
            <span className="w">
              <span>
                {c.campaign} <span className="kc-caption">· {c.channel}</span>
              </span>
              <span className="kc-caption">
                Costs more than it brings in: spent <FactNumber fact={c.spend} />, sales from it{" "}
                <FactNumber fact={c.attributed_sales} />
              </span>
            </span>
            <FactNumber fact={c.roas} tone="negative" />
          </li>
        ))}
        {ads?.best_channel ? (
          <li>
            <span className="w">
              <span>Best ad channel: {ads.best_channel}</span>
              <span className="kc-caption">
                Return on ad spend; total ad spend <FactNumber fact={ads.total_spend} />
              </span>
            </span>
            <FactNumber fact={ads.best_channel_roas} tone="positive" />
          </li>
        ) : null}
      </ul>
    </Card>
  );
}

function Row({ label, line, metric }: { label: string; line: ProductLine; metric: "margin" | "cover" }) {
  const fact = metric === "margin" ? line.margin : line.days_of_cover;
  const tone = label === "Best margin" ? "positive" : label === "Weakest margin" ? "default" : "negative";
  return (
    <li>
      <span className="w">
        <span>{line.name}</span>
        <span className="kc-caption">{metric === "margin" ? label : `${label}: stock left for`}</span>
      </span>
      <FactNumber fact={fact} tone={tone} />
    </li>
  );
}

/** What the owner skipped at onboarding, and what adding it would let me check. */
export function CouldAlsoCheck({ hints }: { hints: string[] | undefined }) {
  if (!hints?.length) return null;
  return (
    <div className="ka-hints">
      {hints.map((h) => (
        <p key={h} className="kc-caption">
          <Lightbulb size={14} strokeWidth={1.5} aria-hidden /> {h}
        </p>
      ))}
    </div>
  );
}
