"""Filterung und Sortierung des Katalogs."""

from __future__ import annotations

from hive.catalog import (
    CatalogFilter,
    OpenRouterModel,
    Role,
    SortKey,
    apply_filter,
    provider_facets,
)


def ids(models: list[OpenRouterModel], criteria: CatalogFilter) -> list[str]:
    return [s.id for s in apply_filter(models, criteria)]


def test_search_matches_id_and_description(sample_models: list[OpenRouterModel]) -> None:
    assert ids(sample_models, CatalogFilter(search="claude")) == ["anthropic/claude-sonnet"]
    assert len(ids(sample_models, CatalogFilter(search="Testmodell"))) == len(sample_models)


def test_role_filter_uses_derived_capabilities(sample_models: list[OpenRouterModel]) -> None:
    inspectors = ids(sample_models, CatalogFilter(role=Role.INSPECTOR))
    assert set(inspectors) == {"anthropic/claude-sonnet", "openai/gpt-mini"}

    # Jedes Modell taugt als Scout — auch die ohne Tool-Calling.
    assert len(ids(sample_models, CatalogFilter(role=Role.SCOUT))) == len(sample_models)


def test_price_filter_excludes_unknown_pricing(sample_models: list[OpenRouterModel]) -> None:
    """Ein Modell ohne bekannten Preis darf keinen Preisfilter passieren."""
    result = ids(sample_models, CatalogFilter(max_blended_usd_per_mtok=1.0))
    assert "obscure/no-price" not in result
    assert "mistralai/mistral-small" in result


def test_free_only(sample_models: list[OpenRouterModel]) -> None:
    assert ids(sample_models, CatalogFilter(free_only=True)) == ["meta/llama-text"]


def test_filters_are_combined_with_and(sample_models: list[OpenRouterModel]) -> None:
    criteria = CatalogFilter(
        supports_tools=True, supports_vision=True, max_blended_usd_per_mtok=1.0
    )
    assert ids(sample_models, criteria) == ["openai/gpt-mini"]


def test_price_sort_puts_unknown_last(sample_models: list[OpenRouterModel]) -> None:
    ascending = ids(sample_models, CatalogFilter(sort=SortKey.PRICE_ASC))
    assert ascending[0] == "meta/llama-text"
    assert ascending[-1] == "obscure/no-price"

    descending = ids(sample_models, CatalogFilter(sort=SortKey.PRICE_DESC))
    assert descending[0] == "anthropic/claude-sonnet"
    # Auch bei umgekehrter Richtung bleibt Unbekanntes hinten.
    assert descending[-1] == "obscure/no-price"


def test_min_context_filter(sample_models: list[OpenRouterModel]) -> None:
    assert ids(sample_models, CatalogFilter(min_context_length=1_000_000)) == []
    assert len(ids(sample_models, CatalogFilter(min_context_length=128_000))) == len(sample_models)


def test_provider_facets_sorted_by_count(sample_models: list[OpenRouterModel]) -> None:
    facets = provider_facets(sample_models)
    assert {f.provider for f in facets} == {
        "anthropic",
        "openai",
        "mistralai",
        "meta",
        "obscure",
    }
    assert all(f.count == 1 for f in facets)
