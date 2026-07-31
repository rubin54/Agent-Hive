"""Catalog service: ties together fetching, storage and fallback."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .client import CatalogFetchError, fetch_models
from .models import OpenRouterModel
from .store import CatalogStore, Snapshot


@dataclass(frozen=True, slots=True)
class CatalogState:
    snapshot: Snapshot
    is_fixture: bool

    @property
    def models(self) -> list[OpenRouterModel]:
        return self.snapshot.models


class CatalogUnavailableError(RuntimeError):
    """Neither a snapshot nor the bundled fixture is available."""


class CatalogService:
    """Serves the current catalog state and triggers synchronisations.

    The load order is deliberate: newest snapshot before bundled fixture. A freshly cloned
    installation works immediately with real data, while a synced system always uses the
    current state.
    """

    def __init__(self, store: CatalogStore, *, fixture_path: Path, source: str) -> None:
        self._store = store
        self._fixture_path = fixture_path
        self._source = source
        self._cache: CatalogState | None = None

    def current(self) -> CatalogState:
        if self._cache is not None:
            return self._cache

        snapshot = self._store.load_latest()
        if snapshot is not None:
            self._cache = CatalogState(snapshot=snapshot, is_fixture=False)
            return self._cache

        if self._fixture_path.is_file():
            fixture = CatalogStore.read_file(self._fixture_path)
            if fixture is not None:
                self._cache = CatalogState(snapshot=fixture, is_fixture=True)
                return self._cache

        raise CatalogUnavailableError(
            "No catalog available. Run 'hive catalog sync' once — the OpenRouter endpoint "
            "is public and needs no API key."
        )

    def snapshot_ids(self) -> list[str]:
        return self._store.list_snapshot_ids()

    def load(self, snapshot_id: str) -> Snapshot | None:
        return self._store.load(snapshot_id)

    async def sync(self, *, timeout: float = 30.0) -> Snapshot:
        models, raw = await fetch_models(url=self._source, timeout=timeout)
        snapshot = self._store.save(models, raw, source=self._source)
        self._cache = CatalogState(snapshot=snapshot, is_fixture=False)
        return snapshot


__all__ = [
    "CatalogFetchError",
    "CatalogService",
    "CatalogState",
    "CatalogUnavailableError",
]
