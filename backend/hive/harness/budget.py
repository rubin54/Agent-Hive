"""Budget enforcement.

A hard boundary, not a suggestion: once a limit is reached, the run ends. Without it a
goal-driven loop burns arbitrary amounts of money — and that is exactly where most home-grown
harnesses fail visibly.

Costs are computed exclusively in ``Decimal``. At prices around 1e-7 per token, float rounding
errors accumulate into visible drift across tens of thousands of calls — and in this project
the cost axis is a measurement, not an afterthought.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum

from ..catalog.models import Pricing
from .messages import Usage


class LimitKind(StrEnum):
    ITERATIONS = "iterations"
    TOKENS = "tokens"
    WALL_CLOCK = "wall_clock"
    COST = "cost"


class BudgetExceeded(Exception):
    """A hard limit was reached."""

    def __init__(self, kind: LimitKind, detail: str) -> None:
        super().__init__(detail)
        self.kind = kind
        self.detail = detail


@dataclass(frozen=True, slots=True)
class BudgetLimits:
    """Upper bounds of a run.

    ``max_cost_usd`` is deliberately the emergency brake and not the comparison variable:
    model-versus-model is capped by iterations and tokens so a cheap model does not simply
    get more attempts. Only when comparing swarm against solo (from M5) is dollar parity the
    right control variable.
    """

    max_iterations: int = 20
    max_tokens: int | None = 200_000
    max_wall_clock_seconds: float | None = 900.0
    max_cost_usd: Decimal | None = Decimal("5.00")


@dataclass(slots=True)
class BudgetSnapshot:
    iterations: int
    usage: Usage
    cost_usd: Decimal
    elapsed_seconds: float

    def format(self) -> str:
        return (
            f"{self.iterations} iterations · {self.usage.total_tokens:,} tokens · "
            f"${self.cost_usd:.4f} · {self.elapsed_seconds:.1f}s"
        )


@dataclass(slots=True)
class BudgetTracker:
    limits: BudgetLimits
    pricing: Pricing | None = None
    iterations: int = 0
    usage: Usage = field(default_factory=Usage)
    cost_usd: Decimal = Decimal(0)
    _started_at: float = field(default_factory=time.monotonic)

    @property
    def elapsed_seconds(self) -> float:
        return time.monotonic() - self._started_at

    def snapshot(self) -> BudgetSnapshot:
        return BudgetSnapshot(
            iterations=self.iterations,
            usage=self.usage,
            cost_usd=self.cost_usd,
            elapsed_seconds=self.elapsed_seconds,
        )

    def cost_of(self, usage: Usage) -> Decimal:
        """Cost of one call derived from catalog prices.

        Without known prices the cost axis stays at zero — more honest than an estimate, and
        the catalog already marks such models as price-less.
        """
        if self.pricing is None:
            return Decimal(0)
        prompt_price = self.pricing.prompt or Decimal(0)
        completion_price = self.pricing.completion or Decimal(0)
        # Providers bill reasoning tokens like output tokens.
        completion_tokens = usage.completion_tokens + usage.reasoning_tokens
        return prompt_price * usage.prompt_tokens + completion_price * completion_tokens

    def record(self, usage: Usage, *, reported_cost_usd: Decimal | None = None) -> Decimal:
        """Book a model call and return its cost."""
        self.usage = self.usage + usage
        # When the provider reports real cost, that wins over our own arithmetic — it
        # accounts for discounts and cache hits the catalog price knows nothing about.
        cost = reported_cost_usd if reported_cost_usd is not None else self.cost_of(usage)
        self.cost_usd += cost
        return cost

    def start_iteration(self) -> None:
        """Check every limit and count the iteration. Raises when exceeded."""
        if self.iterations >= self.limits.max_iterations:
            raise BudgetExceeded(
                LimitKind.ITERATIONS,
                f"Iteration limit reached ({self.limits.max_iterations})",
            )
        if self.limits.max_tokens is not None and self.usage.total_tokens >= self.limits.max_tokens:
            raise BudgetExceeded(
                LimitKind.TOKENS,
                f"Token limit reached ({self.usage.total_tokens:,} / {self.limits.max_tokens:,})",
            )
        if (
            self.limits.max_wall_clock_seconds is not None
            and self.elapsed_seconds >= self.limits.max_wall_clock_seconds
        ):
            raise BudgetExceeded(
                LimitKind.WALL_CLOCK,
                f"Time limit reached ({self.elapsed_seconds:.0f}s)",
            )
        if self.limits.max_cost_usd is not None and self.cost_usd >= self.limits.max_cost_usd:
            raise BudgetExceeded(
                LimitKind.COST,
                f"Cost limit reached (${self.cost_usd:.4f} / ${self.limits.max_cost_usd})",
            )
        self.iterations += 1


def estimate_cost(
    pricing: Pricing, *, prompt_tokens: int, completion_tokens: int
) -> Decimal | None:
    """Up-front estimate for the sweep cost preview (from M4)."""
    if pricing.prompt is None or pricing.completion is None:
        return None
    return pricing.prompt * prompt_tokens + pricing.completion * completion_tokens
