"""Configuration. Everything via environment variables with the ``HIVE_`` prefix."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/hive/config.py -> backend/hive -> backend -> repository root
REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="HIVE_", env_file=".env", extra="ignore")

    data_dir: Path = REPO_ROOT / "data"
    catalog_source: str = "https://openrouter.ai/api/v1/models"
    catalog_timeout_seconds: float = 30.0

    # Only passed through to OpenRouter. Never persisted; the public demo runs on recorded
    # runs rather than live calls.
    openrouter_api_key: str = ""

    sandbox_image: str = "hive/node-web:1"
    sandbox_memory_mb: int = 2048
    sandbox_cpus: float = 2.0
    # Default "none": the egress proxy with an allowlist is still missing (see PLAN.md).
    # Anyone letting a model install packages switches to "internal" deliberately.
    sandbox_network: str = "none"

    templates_dir: Path = REPO_ROOT / "templates"

    # CORS for the Vite dev server. In production FastAPI serves the frontend statically,
    # so the list is empty then.
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]

    @property
    def catalog_dir(self) -> Path:
        return self.data_dir / "catalog"

    @property
    def screenshots_dir(self) -> Path:
        return self.data_dir / "screenshots"

    @property
    def fixture_path(self) -> Path:
        """Bundled snapshot so the demo runs without network and without a key."""
        return Path(__file__).resolve().parent / "catalog" / "fixture.json"


@lru_cache
def get_settings() -> Settings:
    return Settings()
