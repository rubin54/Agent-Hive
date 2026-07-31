"""Modellkatalog: Abruf von OpenRouter, Fähigkeitsableitung, versionierte Snapshots."""

from .capabilities import Capabilities, Role, derive_capabilities
from .client import CatalogFetchError, fetch_models
from .models import Architecture, OpenRouterModel, Pricing, ReasoningInfo, TopProvider
from .query import (
    CatalogFilter,
    CatalogPage,
    ModelSummary,
    ProviderFacet,
    SortKey,
    apply_filter,
    paginate,
    provider_facets,
    to_summary,
)
from .service import CatalogService, CatalogState, CatalogUnavailableError
from .store import CatalogStore, Snapshot

__all__ = [
    "Architecture",
    "Capabilities",
    "CatalogFetchError",
    "CatalogFilter",
    "CatalogPage",
    "CatalogService",
    "CatalogState",
    "CatalogStore",
    "CatalogUnavailableError",
    "ModelSummary",
    "OpenRouterModel",
    "Pricing",
    "ProviderFacet",
    "ReasoningInfo",
    "Role",
    "Snapshot",
    "SortKey",
    "TopProvider",
    "apply_filter",
    "derive_capabilities",
    "fetch_models",
    "paginate",
    "provider_facets",
    "to_summary",
]
