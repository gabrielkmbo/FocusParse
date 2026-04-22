"""USD pricing for model calls.

The table below tracks **published list prices in USD per 1M tokens** as of
2026-04. This is the only place costs are computed — model clients call
`compute_usd(provider, model, tokens_in, tokens_out)` and tuck the result on
`ModelResponse.usd`. Downstream aggregation (`eval/metrics.py`) sums across
per-example records.

Kept simple on purpose:
  - No cached-prompt tier (we don't use prompt caching in v1).
  - No image-token surcharge broken out — image cost is bundled into input
    tokens by every provider's billing today. If that changes, add a
    per-image-megapixel term here.
  - Unknown (provider, model) pairs return `None` (= "unpriced"); metrics
    downstream should treat that as `0.0` for `usd_total`.

Update cadence: bump when a provider price-sheet changes. Rows are versioned
by the date comment above the tuple — don't delete old rows, comment them out
so historical runs still score.
"""

from __future__ import annotations

# (provider, model) → (input_usd_per_mtok, output_usd_per_mtok)
_PRICING: dict[tuple[str, str], tuple[float, float]] = {
    # OpenAI — 2026-04 list prices
    ("openai", "gpt-5.4"): (1.25, 10.00),
    ("openai", "gpt-5.4-mini"): (0.25, 2.00),
    ("openai", "gpt-4o"): (2.50, 10.00),
    ("openai", "gpt-4o-mini"): (0.15, 0.60),
    # Anthropic — 2026-04 list prices
    ("anthropic", "claude-opus-4-6"): (15.00, 75.00),
    ("anthropic", "claude-sonnet-4-6"): (3.00, 15.00),
    ("anthropic", "claude-haiku-4-5"): (0.80, 4.00),
    # Gemini — 2026-04 list prices (Vertex public preview)
    ("gemini", "gemini-3.1-pro-preview"): (1.25, 10.00),
    ("gemini", "gemini-3.1-flash-preview"): (0.075, 0.30),
}


def compute_usd(
    provider: str,
    model: str,
    tokens_in: int,
    tokens_out: int,
) -> float | None:
    """Return USD cost for a single model call, or `None` if unpriced.

    Treat `None` downstream as "don't add to usd_total" — aggregating across
    unpriced and priced calls silently would understate reality.
    """
    key = (provider.lower(), model)
    if key not in _PRICING:
        return None
    in_price, out_price = _PRICING[key]
    return (tokens_in / 1_000_000) * in_price + (tokens_out / 1_000_000) * out_price


def is_priced(provider: str, model: str) -> bool:
    return (provider.lower(), model) in _PRICING


__all__ = ["compute_usd", "is_priced"]
