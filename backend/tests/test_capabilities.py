"""Role eligibility — the core logic of M0."""

from __future__ import annotations

from decimal import Decimal

from hive.catalog import Role, derive_capabilities

from .conftest import make_model


def test_scout_role_needs_no_tools() -> None:
    """Scouts plan in text. A model without tool calling stays scout-eligible."""
    caps = derive_capabilities(make_model(tools=False))
    assert caps.roles == [Role.SCOUT]
    assert caps.ineligible_reason is not None


def test_tools_unlock_worker_and_queen() -> None:
    caps = derive_capabilities(make_model(tools=True))
    assert Role.WORKER in caps.roles
    assert Role.QUEEN in caps.roles
    assert Role.INSPECTOR not in caps.roles
    assert caps.ineligible_reason is None


def test_vision_unlocks_inspector() -> None:
    caps = derive_capabilities(make_model(tools=True, vision=True))
    assert set(caps.roles) == {Role.SCOUT, Role.WORKER, Role.QUEEN, Role.INSPECTOR}


def test_vision_without_tools_is_inspector_but_not_worker() -> None:
    caps = derive_capabilities(make_model(tools=False, vision=True))
    assert Role.INSPECTOR in caps.roles
    assert Role.WORKER not in caps.roles


def test_free_model_detected() -> None:
    assert derive_capabilities(make_model(prompt="0", completion="0")).is_free


def test_unknown_price_is_not_free() -> None:
    """A missing price means unknown, not free.

    Confusing the two would be expensive: a model on a variable rate would slip into every
    free filter and undermine cost estimation.
    """
    caps = derive_capabilities(make_model(prompt=None, completion=None))
    assert not caps.is_free


def test_negative_price_means_unknown() -> None:
    """OpenRouter uses "-1" for variable rates."""
    model = make_model(prompt="-1", completion="-1")
    assert model.pricing.prompt is None
    assert model.pricing.blended_per_mtok is None


def test_pricing_stays_decimal() -> None:
    """Prices are never computed through float — binary errors would accumulate."""
    model = make_model(prompt="0.00000014", completion="0.00000028")
    assert isinstance(model.pricing.prompt, Decimal)
    assert model.pricing.prompt_per_mtok == Decimal("0.14")
    # 0.75 * 0.14 + 0.25 * 0.28
    assert model.pricing.blended_per_mtok == Decimal("0.175")


def test_malformed_model_does_not_break_parsing() -> None:
    """Missing sub-objects do occur in the real response."""
    model = make_model()
    payload = model.model_dump()
    payload["architecture"] = None
    payload["pricing"] = None
    payload["supported_parameters"] = None

    from hive.catalog import OpenRouterModel

    revived = OpenRouterModel.model_validate(payload)
    assert revived.architecture.input_modalities == []
    assert derive_capabilities(revived).roles == [Role.SCOUT]
