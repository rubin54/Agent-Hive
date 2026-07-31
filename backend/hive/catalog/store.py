"""Versionierte Snapshot-Ablage für den Modellkatalog.

Snapshots sind unveränderlich. Ein Benchmark-Ergebnis von morgen muss auf den Modell- und
Preisstand von morgen verweisen können — sonst vergleicht man nach drei Wochen Äpfel mit
Birnen, ohne es zu merken.

M0 speichert als JSON auf der Platte. Ab M4 (Sweeps) wandert das Ganze nach Postgres; die
Schnittstelle hier ist so geschnitten, dass der Tausch nur diese Datei betrifft.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .models import OpenRouterModel

SNAPSHOT_PREFIX = "snapshot-"
SNAPSHOT_SUFFIX = ".json"
_TIMESTAMP_FORMAT = "%Y%m%dT%H%M%SZ"


@dataclass(frozen=True, slots=True)
class Snapshot:
    """Ein eingefrorener Katalogstand."""

    snapshot_id: str
    synced_at: datetime
    source: str
    models: list[OpenRouterModel]

    @property
    def model_count(self) -> int:
        return len(self.models)


class CatalogStore:
    def __init__(self, directory: Path) -> None:
        self.directory = directory

    # ---------------------------------------------------------------- schreiben

    def save(
        self,
        models: list[OpenRouterModel],
        raw: list[dict[str, Any]],
        *,
        source: str,
        synced_at: datetime | None = None,
    ) -> Snapshot:
        self.directory.mkdir(parents=True, exist_ok=True)
        stamp = (synced_at or datetime.now(UTC)).astimezone(UTC)
        snapshot_id = stamp.strftime(_TIMESTAMP_FORMAT)
        path = self.directory / f"{SNAPSHOT_PREFIX}{snapshot_id}{SNAPSHOT_SUFFIX}"

        document = {
            "snapshot_id": snapshot_id,
            "synced_at": stamp.isoformat(),
            "source": source,
            "model_count": len(models),
            "models": raw,
        }
        # Erst daneben schreiben, dann umbenennen: ein abgebrochener Sync darf keinen
        # halben Snapshot hinterlassen, den der nächste Start für gültig hält.
        temp = path.with_suffix(".partial")
        temp.write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8")
        temp.replace(path)

        return Snapshot(
            snapshot_id=snapshot_id, synced_at=stamp, source=source, models=list(models)
        )

    # ------------------------------------------------------------------- lesen

    def list_snapshot_ids(self) -> list[str]:
        """Snapshot-IDs, neueste zuerst."""
        if not self.directory.is_dir():
            return []
        ids = [
            path.name[len(SNAPSHOT_PREFIX) : -len(SNAPSHOT_SUFFIX)]
            for path in self.directory.glob(f"{SNAPSHOT_PREFIX}*{SNAPSHOT_SUFFIX}")
        ]
        return sorted(ids, reverse=True)

    def load(self, snapshot_id: str) -> Snapshot | None:
        path = self.directory / f"{SNAPSHOT_PREFIX}{snapshot_id}{SNAPSHOT_SUFFIX}"
        if not path.is_file():
            return None
        return self._read(path)

    def load_latest(self) -> Snapshot | None:
        ids = self.list_snapshot_ids()
        return self.load(ids[0]) if ids else None

    @staticmethod
    def read_file(path: Path) -> Snapshot | None:
        return CatalogStore._read(path)

    @staticmethod
    def _read(path: Path) -> Snapshot | None:
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(document, dict):
            return None

        models: list[OpenRouterModel] = []
        for entry in document.get("models", []):
            if not isinstance(entry, dict):
                continue
            try:
                models.append(OpenRouterModel.model_validate(entry))
            except ValueError:
                continue

        raw_time = document.get("synced_at")
        try:
            synced_at = datetime.fromisoformat(str(raw_time))
        except (TypeError, ValueError):
            synced_at = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)

        return Snapshot(
            snapshot_id=str(document.get("snapshot_id") or path.stem),
            synced_at=synced_at,
            source=str(document.get("source") or "unbekannt"),
            models=models,
        )
