"""Per-model token prices, used by the adapter to enforce the local LLM_BUDGET_USD cap.

Prices are integer micro-USD per 1M tokens (so $2.00 / 1M is 2_000_000), and costs are integer micro-USD rounded
up, so the audit log never carries floats (canonical JSON refuses them) and the cap errs on the side of stopping
early. An unknown model is priced at the most expensive known rate: a renamed or mistyped model can make the budget
run out sooner, never later.

Sources (checked 2026-10-18; re-check before the final recording):
- gpt-5.6-terra: OpenAI model page, $2.00 in / $0.20 cached in / $12.00 out.
- gpt-5.6-sol: $5.00 in / $0.50 cached in / $30.00 out.
- gemini-2.5-flash: $0.30 in / $2.50 out (no cached-input discount assumed).
"""

from dataclasses import dataclass

from app.llm.types import Usage


@dataclass(frozen=True)
class Price:
    """Micro-USD per 1M tokens."""

    input: int
    cached_input: int
    output: int


PRICES: dict[str, Price] = {
    "gpt-5.6-terra": Price(input=2_000_000, cached_input=200_000, output=12_000_000),
    "gpt-5.6-sol": Price(input=5_000_000, cached_input=500_000, output=30_000_000),
    "gemini-2.5-flash": Price(input=300_000, cached_input=300_000, output=2_500_000),
}

CONSERVATIVE = Price(
    input=max(p.input for p in PRICES.values()),
    cached_input=max(p.input for p in PRICES.values()),
    output=max(p.output for p in PRICES.values()),
)


def price_for(model: str) -> tuple[Price, bool]:
    """The model's price and whether it is known. Dated snapshots (`gpt-5.6-terra-2026-08-01`) match their base."""
    if model in PRICES:
        return PRICES[model], True
    for name, price in PRICES.items():
        if model.startswith(name + "-"):
            return price, True
    return CONSERVATIVE, False


def _ceil_div(a: int, b: int) -> int:
    return -(-a // b)


def cost_microusd(model: str, usage: Usage) -> int:
    """Cost of one call in micro-USD, rounded up. Cached input tokens are a subset of input tokens."""
    price, _ = price_for(model)
    cached = min(usage.cached_input_tokens, usage.input_tokens)
    total = (
        (usage.input_tokens - cached) * price.input
        + cached * price.cached_input
        + usage.output_tokens * price.output
    )
    return _ceil_div(total, 1_000_000)


def usd_to_microusd(usd: float) -> int:
    return int(round(usd * 1_000_000))
