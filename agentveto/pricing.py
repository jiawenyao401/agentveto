"""Model pricing. Values are USD per 1,000,000 tokens as (input, output).

These numbers go stale, and vendors change them without notice. Override any
time with ``agentveto.set_pricing({...})`` or load your own table from JSON.

Design decision: an unknown model is priced at 0 and flagged, never guessed.
A wrong cost number is worse than a missing one - someone will make a budget
decision off it.
"""

from __future__ import annotations

_DEFAULT_PRICING: dict[str, tuple[float, float]] = {
    # OpenAI
    "gpt-4o": (2.50, 10.00),
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4.1": (2.00, 8.00),
    "gpt-4.1-mini": (0.40, 1.60),
    "gpt-4.1-nano": (0.10, 0.40),
    "o3": (2.00, 8.00),
    "o4-mini": (1.10, 4.40),
    # Anthropic
    "claude-opus-4": (15.00, 75.00),
    "claude-sonnet-4": (3.00, 15.00),
    "claude-3-5-sonnet": (3.00, 15.00),
    "claude-3-5-haiku": (0.80, 4.00),
    # DeepSeek
    "deepseek-chat": (0.27, 1.10),
    "deepseek-reasoner": (0.55, 2.19),
    # Qwen
    "qwen-plus": (0.40, 1.20),
    "qwen-max": (1.60, 6.40),
    "qwen-turbo": (0.05, 0.20),
    # Moonshot
    "moonshot-v1-8k": (0.80, 0.80),
    "moonshot-v1-32k": (1.60, 1.60),
    # Zhipu
    "glm-4": (1.40, 1.40),
    "glm-4-flash": (0.00, 0.00),
}

_table: dict[str, tuple[float, float]] = dict(_DEFAULT_PRICING)


def set_pricing(table: dict[str, tuple[float, float]], *, replace: bool = False) -> None:
    """Override or extend the pricing table. Tuples are (input, output) per 1M tokens."""
    global _table
    if replace:
        _table = {}
    _table.update(table)


def get_pricing() -> dict[str, tuple[float, float]]:
    return dict(_table)


def resolve(model: str | None) -> tuple[float, float] | None:
    """Find the price for a model. Handles dated suffixes like ``gpt-4o-2024-11-20``.

    Returns None when unknown so callers can mark the span instead of inventing a number.
    """
    if not model:
        return None
    key = model.strip().lower()
    if key in _table:
        return _table[key]

    # Longest-prefix match against known names, so "gpt-4o-2024-11-20" hits "gpt-4o".
    best: tuple[str, tuple[float, float]] | None = None
    for name, price in _table.items():
        if key.startswith(name) and (best is None or len(name) > len(best[0])):
            best = (name, price)
    return best[1] if best else None


def cost(model: str | None, tokens_in: int, tokens_out: int) -> tuple[float, bool]:
    """Return (cost_usd, pricing_known)."""
    price = resolve(model)
    if price is None:
        return 0.0, False
    pin, pout = price
    return (tokens_in / 1_000_000.0) * pin + (tokens_out / 1_000_000.0) * pout, True
