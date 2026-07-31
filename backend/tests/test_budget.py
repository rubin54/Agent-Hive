"""Budget enforcement and cost arithmetic."""

from __future__ import annotations

from decimal import Decimal

import pytest

from hive.catalog.models import Pricing
from hive.harness.budget import BudgetExceeded, BudgetLimits, BudgetTracker, LimitKind
from hive.harness.messages import Usage


def tracker(**limits: object) -> BudgetTracker:
    defaults: dict[str, object] = {
        "max_iterations": 10,
        "max_tokens": None,
        "max_wall_clock_seconds": None,
        "max_cost_usd": None,
    }
    defaults.update(limits)
    return BudgetTracker(limits=BudgetLimits(**defaults))  # type: ignore[arg-type]


def test_iteration_limit_is_hard() -> None:
    budget = tracker(max_iterations=2)
    budget.start_iteration()
    budget.start_iteration()
    with pytest.raises(BudgetExceeded) as exc:
        budget.start_iteration()
    assert exc.value.kind is LimitKind.ITERATIONS


def test_token_limit_is_hard() -> None:
    budget = tracker(max_tokens=100)
    budget.start_iteration()
    budget.record(Usage(prompt_tokens=90, completion_tokens=20))
    with pytest.raises(BudgetExceeded) as exc:
        budget.start_iteration()
    assert exc.value.kind is LimitKind.TOKENS


def test_cost_limit_is_hard() -> None:
    budget = BudgetTracker(
        limits=BudgetLimits(
            max_iterations=99,
            max_tokens=None,
            max_wall_clock_seconds=None,
            max_cost_usd=Decimal("0.01"),
        ),
        pricing=Pricing.model_validate({"prompt": "0.001", "completion": "0.002"}),
    )
    budget.start_iteration()
    budget.record(Usage(prompt_tokens=10, completion_tokens=10))  # 0.01 + 0.02
    with pytest.raises(BudgetExceeded) as exc:
        budget.start_iteration()
    assert exc.value.kind is LimitKind.COST


def test_cost_is_decimal_all_the_way() -> None:
    """At prices around 1e-7 per token, float errors accumulate visibly."""
    pricing = Pricing.model_validate({"prompt": "0.00000014", "completion": "0.00000028"})
    budget = BudgetTracker(limits=BudgetLimits(), pricing=pricing)
    for _ in range(10_000):
        budget.record(Usage(prompt_tokens=1, completion_tokens=1))

    assert isinstance(budget.cost_usd, Decimal)
    # Exactly: 10000 * (0.00000014 + 0.00000028)
    assert budget.cost_usd == Decimal("0.0042")


def test_reasoning_tokens_are_billed_like_output() -> None:
    pricing = Pricing.model_validate({"prompt": "0", "completion": "0.00001"})
    budget = BudgetTracker(limits=BudgetLimits(), pricing=pricing)
    budget.record(Usage(prompt_tokens=0, completion_tokens=10, reasoning_tokens=90))
    assert budget.cost_usd == Decimal("0.001")


def test_reported_cost_wins_over_own_calculation() -> None:
    """Reported cost knows about discounts and cache hits the catalog price cannot see."""
    pricing = Pricing.model_validate({"prompt": "0.001", "completion": "0.001"})
    budget = BudgetTracker(limits=BudgetLimits(), pricing=pricing)
    charged = budget.record(
        Usage(prompt_tokens=1000, completion_tokens=1000), reported_cost_usd=Decimal("0.5")
    )
    assert charged == Decimal("0.5")
    assert budget.cost_usd == Decimal("0.5")


def test_unknown_pricing_keeps_cost_at_zero() -> None:
    """Without prices the cost axis stays empty rather than estimated."""
    budget = BudgetTracker(limits=BudgetLimits(), pricing=None)
    budget.record(Usage(prompt_tokens=10_000, completion_tokens=10_000))
    assert budget.cost_usd == Decimal(0)


def test_snapshot_reports_everything() -> None:
    budget = tracker()
    budget.start_iteration()
    budget.record(Usage(prompt_tokens=5, completion_tokens=7))
    snapshot = budget.snapshot()
    assert snapshot.iterations == 1
    assert snapshot.usage.total_tokens == 12
    assert "1 iterations" in snapshot.format()
