"""Projection, filtering and sorting of the catalog for the dashboard.

Prices are converted from ``Decimal`` to ``float`` here — but *only* for display. All
arithmetic (cost estimates, budget enforcement, accounting) stays in ``Decimal``. Keeping
that split clean matters from M1 onwards, when real money is involved.
"""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field

from .capabilities import Role, derive_capabilities
from .models import OpenRouterModel


class SortKey(StrEnum):
    NAME = "name"
    PRICE_ASC = "price_asc"
    PRICE_DESC = "price_desc"
    CONTEXT_DESC = "context_desc"
    NEWEST = "newest"


class ModelSummary(BaseModel):
    """Everything a dashboard tile needs."""

    id: str
    name: str
    provider: str
    description: str | None = None
    created: int | None = None

    context_length: int | None = None
    max_completion_tokens: int | None = None

    prompt_usd_per_mtok: float | None = None
    completion_usd_per_mtok: float | None = None
    blended_usd_per_mtok: float | None = None
    pricing_known: bool = True

    supports_tools: bool
    supports_vision: bool
    supports_structured_output: bool
    is_free: bool
    reasoning_efforts: list[str] = Field(default_factory=list)

    roles: list[Role]
    ineligible_reason: str | None = None


class ProviderFacet(BaseModel):
    provider: str
    count: int


class CatalogPage(BaseModel):
    snapshot_id: str
    synced_at: str
    total: int
    offset: int
    limit: int
    items: list[ModelSummary]


def _as_float(value: Decimal | None) -> float | None:
    return None if value is None else float(value)


def to_summary(model: OpenRouterModel) -> ModelSummary:
    caps = derive_capabilities(model)
    pricing = model.pricing
    return ModelSummary(
        id=model.id,
        name=model.name,
        provider=model.provider,
        description=model.description,
        created=model.created,
        context_length=model.effective_context_length,
        max_completion_tokens=model.top_provider.max_completion_tokens,
        prompt_usd_per_mtok=_as_float(pricing.prompt_per_mtok),
        completion_usd_per_mtok=_as_float(pricing.completion_per_mtok),
        blended_usd_per_mtok=_as_float(pricing.blended_per_mtok),
        pricing_known=pricing.prompt is not None and pricing.completion is not None,
        supports_tools=caps.supports_tools,
        supports_vision=caps.supports_vision,
        supports_structured_output=caps.supports_structured_output,
        is_free=caps.is_free,
        reasoning_efforts=model.reasoning.supported_efforts if model.reasoning else [],
        roles=caps.roles,
        ineligible_reason=caps.ineligible_reason,
    )


class CatalogFilter(BaseModel):
    """Dashboard filter criteria. Every field is optional and additive (AND-combined)."""

    search: str | None = None
    provider: str | None = None
    role: Role | None = None
    supports_tools: bool | None = None
    supports_vision: bool | None = None
    free_only: bool = False
    max_blended_usd_per_mtok: float | None = None
    min_context_length: int | None = None
    sort: SortKey = SortKey.NAME

    def matches(self, summary: ModelSummary) -> bool:
        if self.search:
            needle = self.search.casefold()
            haystack = f"{summary.id} {summary.name} {summary.description or ''}".casefold()
            if needle not in haystack:
                return False
        if self.provider and summary.provider != self.provider:
            return False
        if self.role and self.role not in summary.roles:
            return False
        if self.supports_tools is not None and summary.supports_tools != self.supports_tools:
            return False
        if self.supports_vision is not None and summary.supports_vision != self.supports_vision:
            return False
        if self.free_only and not summary.is_free:
            return False
        if self.max_blended_usd_per_mtok is not None:
            price = summary.blended_usd_per_mtok
            # Models with unknown pricing drop out of a price filter — letting them pass
            # silently would undermine cost estimation later on.
            if price is None or price > self.max_blended_usd_per_mtok:
                return False
        if self.min_context_length is None:
            return True
        return (
            summary.context_length is not None and summary.context_length >= self.min_context_length
        )


def _sort_value(sort: SortKey, summary: ModelSummary) -> tuple[int, float | str]:
    """Sort key with stable handling of missing values.

    The first tuple element always pushes entries without a value to the end, regardless of
    direction — otherwise price-less models would lead the "cheapest first" listing.
    """
    match sort:
        case SortKey.NAME:
            return (0, summary.name.casefold())
        case SortKey.PRICE_ASC | SortKey.PRICE_DESC:
            price = summary.blended_usd_per_mtok
            if price is None:
                return (1, 0.0)
            return (0, -price if sort is SortKey.PRICE_DESC else price)
        case SortKey.CONTEXT_DESC:
            context = summary.context_length
            return (1, 0.0) if context is None else (0, -float(context))
        case SortKey.NEWEST:
            created = summary.created
            return (1, 0.0) if created is None else (0, -float(created))


def apply_filter(
    models: list[OpenRouterModel] | list[ModelSummary],
    criteria: CatalogFilter,
) -> list[ModelSummary]:
    summaries = [m if isinstance(m, ModelSummary) else to_summary(m) for m in models]
    kept = [s for s in summaries if criteria.matches(s)]
    return sorted(kept, key=lambda s: _sort_value(criteria.sort, s))


def provider_facets(models: list[OpenRouterModel] | list[ModelSummary]) -> list[ProviderFacet]:
    counts: dict[str, int] = {}
    for model in models:
        provider = model.provider
        counts[provider] = counts.get(provider, 0) + 1
    return [
        ProviderFacet(provider=name, count=count)
        for name, count in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    ]


def paginate(
    items: list[ModelSummary], *, offset: int, limit: int
) -> tuple[list[ModelSummary], int]:
    total = len(items)
    return items[offset : offset + limit], total


RoleLiteral = Literal["scout", "worker", "inspector", "queen"]
