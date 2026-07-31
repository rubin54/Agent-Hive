"""FastAPI application.

This app's OpenAPI schema is the single schema source: the frontend's TypeScript types are
generated from it (``make types``) and never hand-maintained.
"""

from __future__ import annotations

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from ..config import get_settings
from .routes import catalog

API_PREFIX = "/api"


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="Agent Hive",
        version="0.1.0",
        summary="Heterogeneous agent swarm benchmarked against single models",
    )

    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    api = APIRouter(prefix=API_PREFIX)

    @api.get("/health", tags=["meta"])
    def health() -> dict[str, str]:
        return {"status": "ok", "version": app.version}

    api.include_router(catalog.router)
    app.include_router(api)
    return app


app = create_app()
