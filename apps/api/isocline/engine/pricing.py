"""Cost estimation from server-side pricing metadata (model_pricing table). Never hardcoded in business logic."""
from __future__ import annotations


def estimate_cost(pricing: dict | None, input_tokens: int, output_tokens: int, cached_tokens: int = 0) -> float | None:
    if not pricing or pricing.get("input_per_mtok") is None or pricing.get("output_per_mtok") is None:
        return None
    cached_rate = pricing.get("cached_input_per_mtok")
    uncached = max(0, input_tokens - (cached_tokens if cached_rate is not None else 0))
    cost = uncached * pricing["input_per_mtok"] / 1e6 + output_tokens * pricing["output_per_mtok"] / 1e6
    if cached_rate is not None:
        cost += cached_tokens * cached_rate / 1e6
    return cost


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)
