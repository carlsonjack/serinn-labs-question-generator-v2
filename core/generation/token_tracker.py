"""Token usage tracking and cost estimation (EPIC 5, Task 5.4).

After each generation run, logs approximate token usage and estimated cost
so the client is never surprised by the API bill.  Pricing is configurable
via ``model_pricing`` in settings.yaml; unknown models fall back to a
conservative default rate.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# Per-1M-token pricing defaults (USD).  Overridden by settings.yaml
# ``model_pricing`` section when present.
_DEFAULT_PRICING: dict[str, dict[str, float]] = {
    "gpt-4o": {"input": 2.50, "output": 10.00},
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    "gpt-5.4": {"input": 2.50, "output": 10.00},
}

_FALLBACK_PRICING: dict[str, float] = {"input": 5.00, "output": 15.00}


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass
class TokenUsage:
    """Token counts for a single API call."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


@dataclass
class RunCostSummary:
    """Aggregated token usage and estimated cost for an entire run."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    estimated_cost_usd: float = 0.0
    model: str = ""
    batch_usages: list[TokenUsage] = field(default_factory=list)

    @property
    def batch_count(self) -> int:
        return len(self.batch_usages)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def extract_token_usage(response: Any) -> TokenUsage:
    """Pull token counts from an OpenAI API response.

    Safely handles responses where ``usage`` is ``None`` or missing
    (e.g. mocked responses in tests).
    """
    usage = getattr(response, "usage", None)
    if usage is None:
        return TokenUsage()
    return TokenUsage(
        prompt_tokens=getattr(usage, "prompt_tokens", 0) or 0,
        completion_tokens=getattr(usage, "completion_tokens", 0) or 0,
        total_tokens=getattr(usage, "total_tokens", 0) or 0,
    )


def _resolve_pricing(
    model: str, settings: dict[str, Any]
) -> dict[str, float]:
    """Return ``{"input": …, "output": …}`` rates (USD per 1M tokens).

    Checks ``settings["model_pricing"][model]`` first, then built-in
    defaults, then a conservative fallback.
    """
    custom: dict[str, Any] = settings.get("model_pricing", {}) or {}
    if model in custom:
        entry = custom[model]
        return {
            "input": float(entry.get("input", _FALLBACK_PRICING["input"])),
            "output": float(entry.get("output", _FALLBACK_PRICING["output"])),
        }
    if model in _DEFAULT_PRICING:
        return _DEFAULT_PRICING[model]
    return dict(_FALLBACK_PRICING)


def estimate_cost(
    prompt_tokens: int,
    completion_tokens: int,
    model: str,
    settings: dict[str, Any] | None = None,
) -> float:
    """Return the estimated cost in USD for the given token counts."""
    pricing = _resolve_pricing(model, settings or {})
    input_cost = (prompt_tokens / 1_000_000) * pricing["input"]
    output_cost = (completion_tokens / 1_000_000) * pricing["output"]
    return round(input_cost + output_cost, 6)


def build_cost_summary(
    usages: list[TokenUsage],
    model: str,
    settings: dict[str, Any] | None = None,
) -> RunCostSummary:
    """Aggregate per-batch usages into a single :class:`RunCostSummary`."""
    prompt_total = sum(u.prompt_tokens for u in usages)
    completion_total = sum(u.completion_tokens for u in usages)
    total = sum(u.total_tokens for u in usages)

    cost = estimate_cost(prompt_total, completion_total, model, settings)

    return RunCostSummary(
        prompt_tokens=prompt_total,
        completion_tokens=completion_total,
        total_tokens=total,
        estimated_cost_usd=cost,
        model=model,
        batch_usages=list(usages),
    )


def log_cost_summary(summary: RunCostSummary) -> None:
    """Log a human-readable cost summary to the ``generation`` logger."""
    logger.info(
        "Token usage — prompt: %s, completion: %s, total: %s",
        f"{summary.prompt_tokens:,}",
        f"{summary.completion_tokens:,}",
        f"{summary.total_tokens:,}",
    )
    logger.info(
        "Estimated cost — $%.4f USD (model: %s, %d batch(es))",
        summary.estimated_cost_usd,
        summary.model,
        summary.batch_count,
    )
