"""HTTP access to the OpenRouter model catalog.

The endpoint is public — listing models needs **no** API key. That is why M0 works without
any sign-up.
"""

from __future__ import annotations

import httpx

from .models import OpenRouterModel

OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"


class CatalogFetchError(RuntimeError):
    """The catalog could not be loaded."""


async def fetch_models(
    *,
    url: str = OPENROUTER_MODELS_URL,
    timeout: float = 30.0,
    client: httpx.AsyncClient | None = None,
) -> tuple[list[OpenRouterModel], list[dict[str, object]]]:
    """Load the catalog and return parsed models plus the raw payload.

    The raw payload comes along because snapshots store it verbatim: if OpenRouter later adds
    a field we ignore today, old snapshots remain re-analysable.
    """
    owns_client = client is None
    http = client or httpx.AsyncClient(timeout=timeout)
    try:
        response = await http.get(url, headers={"Accept": "application/json"})
        response.raise_for_status()
        payload = response.json()
    except httpx.HTTPError as exc:
        raise CatalogFetchError(f"OpenRouter unreachable: {exc}") from exc
    finally:
        if owns_client:
            await http.aclose()

    raw = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(raw, list):
        raise CatalogFetchError("Unexpected response shape: 'data' list missing")

    models: list[OpenRouterModel] = []
    skipped = 0
    for entry in raw:
        if not isinstance(entry, dict):
            skipped += 1
            continue
        try:
            models.append(OpenRouterModel.model_validate(entry))
        except ValueError:
            # A single broken model must not take down the whole sync.
            skipped += 1

    if not models:
        raise CatalogFetchError(f"Not a single model was parsable ({skipped} discarded)")

    return models, raw
