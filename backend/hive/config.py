"""Konfiguration. Alles über Umgebungsvariablen mit Präfix ``HIVE_``."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/hive/config.py -> backend/hive -> backend -> Repo-Wurzel
REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="HIVE_", env_file=".env", extra="ignore")

    data_dir: Path = REPO_ROOT / "data"
    catalog_source: str = "https://openrouter.ai/api/v1/models"
    catalog_timeout_seconds: float = 30.0

    # CORS für den Vite-Dev-Server. Im Produktivbetrieb liefert FastAPI das Frontend
    # statisch aus, dann ist die Liste leer.
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]

    @property
    def catalog_dir(self) -> Path:
        return self.data_dir / "catalog"

    @property
    def fixture_path(self) -> Path:
        """Mitgelieferter Snapshot, damit die Demo ohne Netz und ohne Key läuft."""
        return Path(__file__).resolve().parent / "catalog" / "fixture.json"


@lru_cache
def get_settings() -> Settings:
    return Settings()
