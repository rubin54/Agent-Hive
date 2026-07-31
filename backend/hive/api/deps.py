"""Dependencies for the API layer."""

from __future__ import annotations

from functools import lru_cache

from ..catalog import CatalogService, CatalogStore
from ..config import get_settings
from ..journal.registry import RunRegistry
from ..journal.store import JournalStore
from ..runs.service import RunService
from ..templates.store import TemplateStore


@lru_cache
def get_catalog_service() -> CatalogService:
    settings = get_settings()
    return CatalogService(
        CatalogStore(settings.catalog_dir),
        fixture_path=settings.fixture_path,
        source=settings.catalog_source,
    )


@lru_cache
def get_template_store() -> TemplateStore:
    return TemplateStore(get_settings().templates_dir)


@lru_cache
def get_journal_store() -> JournalStore:
    return JournalStore(get_settings().runs_dir)


@lru_cache
def get_run_registry() -> RunRegistry:
    # One registry per process — it holds the live runs and their subscribers.
    return RunRegistry()


@lru_cache
def get_run_service() -> RunService:
    settings = get_settings()
    return RunService(
        store=get_journal_store(),
        registry=get_run_registry(),
        templates=get_template_store(),
        catalog=get_catalog_service(),
        screenshot_root=settings.screenshots_dir,
    )
