"""Dependencies for the API layer."""

from __future__ import annotations

from functools import lru_cache

from ..catalog import CatalogService, CatalogStore
from ..config import get_settings


@lru_cache
def get_catalog_service() -> CatalogService:
    settings = get_settings()
    return CatalogService(
        CatalogStore(settings.catalog_dir),
        fixture_path=settings.fixture_path,
        source=settings.catalog_source,
    )
