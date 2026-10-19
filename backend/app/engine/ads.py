"""Advertising: return on ad spend per campaign and per channel. Pure: (ad spend lines, clock) -> Facts.

Return on ad spend (ROAS) = sales the ad platform attributed to the campaign / spend, over the last `window_days`.
Below 1.0x the campaign cost more than the sales it brought in. A campaign without attributed sales gets spend
facts only (its ROAS is unknown, not zero). Every Fact cites the ad spend rows it summed (invariant 4).
"""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta

from app.clock import Clock
from app.engine.common import money, slug
from app.firewall.fact import Fact
from app.ledger.records import AdSpendLine

BY = "engine.ads.return_on_ad_spend"
WINDOW_DAYS = 90


@dataclass(frozen=True)
class Campaign:
    id: str
    name: str
    channel: str
    spend_minor: int
    sales_minor: int | None
    row_ids: tuple[str, ...]

    @property
    def roas(self) -> float | None:
        return self.sales_minor / self.spend_minor if self.sales_minor is not None and self.spend_minor else None


@dataclass(frozen=True)
class AdInsights:
    campaigns: tuple[Campaign, ...] = ()
    losing: tuple[str, ...] = ()  # campaign IDs with ROAS below 1
    best_channel: str | None = None  # channel name (the owner's own label)
    channel_fact: dict[str, str] = field(default_factory=dict)  # channel -> roas fact ID


def roas_fact(fid: str, value: float | None, rows: list[str], inputs: list[str] = ()) -> Fact:
    v = None if value is None else round(value, 2)
    return Fact(id=fid, value=v, unit="ratio", display="not available" if v is None else f"{v:.1f}x",
                source_row_ids=tuple(sorted(set(rows))), inputs=tuple(inputs), computed_by=BY)


def campaign_prefix(campaign_id: str) -> str:
    return f"ads.campaign.{slug(campaign_id)}"


def campaigns(lines: tuple[AdSpendLine, ...], today: date, window_days: int = WINDOW_DAYS) -> list[Campaign]:
    since = today - timedelta(days=window_days)
    grouped: dict[str, list[AdSpendLine]] = defaultdict(list)
    for a in lines:
        if since < a.date <= today:
            grouped[a.campaign_id].append(a)
    out = []
    for cid, rows in sorted(grouped.items()):
        has_sales = any(r.attributed_sales_minor is not None for r in rows)
        out.append(Campaign(id=cid, name=rows[0].campaign, channel=rows[0].channel,
                            spend_minor=sum(r.spend_minor for r in rows),
                            sales_minor=sum(r.attributed_sales_minor or 0 for r in rows) if has_sales else None,
                            row_ids=tuple(r.id for r in rows)))
    return out


def ad_facts(lines: tuple[AdSpendLine, ...], clock: Clock, currency: str,
             window_days: int = WINDOW_DAYS) -> tuple[list[Fact], AdInsights]:
    found = campaigns(lines, clock.today(), window_days)
    if not found:
        return [], AdInsights()
    facts: list[Fact] = []
    for c in found:
        pre, ids = campaign_prefix(c.id), list(c.row_ids)
        facts.append(money(f"{pre}.spend", c.spend_minor, currency, BY, ids))
        if c.sales_minor is not None:
            facts += [money(f"{pre}.attributed_sales", c.sales_minor, currency, BY, ids),
                      roas_fact(f"{pre}.roas", c.roas, ids)]
    all_ids = [i for c in found for i in c.row_ids]
    facts.append(money("ads.total_spend", sum(c.spend_minor for c in found), currency, BY, all_ids))

    by_channel: dict[str, list[Campaign]] = defaultdict(list)
    for c in found:
        if c.sales_minor is not None:
            by_channel[c.channel].append(c)
    channel_fact, channel_roas = {}, {}
    for channel, cs in sorted(by_channel.items()):
        spend = sum(c.spend_minor for c in cs)
        if not spend:
            continue
        channel_roas[channel] = sum(c.sales_minor or 0 for c in cs) / spend
        fid = f"ads.channel.{slug(channel)}.roas"
        channel_fact[channel] = fid
        facts.append(roas_fact(fid, channel_roas[channel], [i for c in cs for i in c.row_ids]))
    best = max(channel_roas, key=lambda ch: (channel_roas[ch], ch)) if len(channel_roas) > 1 else None
    losing = tuple(c.id for c in found if c.roas is not None and c.roas < 1.0)
    return facts, AdInsights(campaigns=tuple(found), losing=losing, best_channel=best, channel_fact=channel_fact)
