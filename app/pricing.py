"""Estimated per-model pricing used for cost observability.

Prices are USD per 1,000 tokens (input / output). They are estimates for
dashboard reporting only — the gateway never bills anyone. Add your own
models here or override the table in one place when prices change.
"""

from __future__ import annotations

# model name -> (input price per 1K tokens, output price per 1K tokens)
PRICE_TABLE: dict[str, tuple[float, float]] = {
    "gpt-4o": (0.0025, 0.0100),
    "gpt-4o-mini": (0.00015, 0.0006),
    "gpt-4-turbo": (0.0100, 0.0300),
    "gpt-3.5-turbo": (0.0005, 0.0015),
    "claude-3-5-sonnet": (0.0030, 0.0150),
    "llama-3.1-70b": (0.0009, 0.0009),
    # The built-in mock provider is free to run; a small nominal price keeps
    # the cost column meaningful in offline demos.
    "mock-1": (0.0001, 0.0002),
}

# Fallback for unknown models.
DEFAULT_PRICE: tuple[float, float] = (0.0010, 0.0020)


def estimate_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    """Return the estimated USD cost of one request."""
    input_price, output_price = PRICE_TABLE.get(model, DEFAULT_PRICE)
    return (prompt_tokens / 1000.0) * input_price + (
        completion_tokens / 1000.0
    ) * output_price


def estimate_tokens(text: str) -> int:
    """Cheap token estimate (~4 characters per token), used when a provider
    does not report usage. Good enough for dashboards and demos."""
    if not text:
        return 0
    return max(1, round(len(text) / 4))
