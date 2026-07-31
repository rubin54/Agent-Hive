"""HTTP-Zugriff auf den OpenRouter-Modellkatalog.

Der Endpunkt ist öffentlich — für das Auflisten der Modelle wird **kein** API-Key benötigt.
Das ist der Grund, warum M0 ohne jede Anmeldung nutzbar ist.
"""

from __future__ import annotations

import httpx

from .models import OpenRouterModel

OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"


class CatalogFetchError(RuntimeError):
    """Der Katalog konnte nicht geladen werden."""


async def fetch_models(
    *,
    url: str = OPENROUTER_MODELS_URL,
    timeout: float = 30.0,
    client: httpx.AsyncClient | None = None,
) -> tuple[list[OpenRouterModel], list[dict[str, object]]]:
    """Lädt den Katalog und gibt geparste Modelle plus Rohdaten zurück.

    Die Rohdaten werden mitgeliefert, weil der Snapshot sie unverändert speichert: Wenn
    OpenRouter später ein Feld ergänzt, das wir heute ignorieren, lassen sich alte Snapshots
    trotzdem neu auswerten.
    """
    owns_client = client is None
    http = client or httpx.AsyncClient(timeout=timeout)
    try:
        response = await http.get(url, headers={"Accept": "application/json"})
        response.raise_for_status()
        payload = response.json()
    except httpx.HTTPError as exc:
        raise CatalogFetchError(f"OpenRouter nicht erreichbar: {exc}") from exc
    finally:
        if owns_client:
            await http.aclose()

    raw = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(raw, list):
        raise CatalogFetchError("Unerwartete Antwortstruktur: 'data'-Liste fehlt")

    models: list[OpenRouterModel] = []
    skipped = 0
    for entry in raw:
        if not isinstance(entry, dict):
            skipped += 1
            continue
        try:
            models.append(OpenRouterModel.model_validate(entry))
        except ValueError:
            # Ein einzelnes kaputtes Modell darf den gesamten Sync nicht kippen.
            skipped += 1

    if not models:
        raise CatalogFetchError(f"Kein einziges Modell parsebar ({skipped} verworfen)")

    return models, raw
