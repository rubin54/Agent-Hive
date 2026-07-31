"""Provider-Abstraktion.

Schmal gehalten: Ein Provider bekommt Nachrichten und Werkzeugschemata und liefert eine
``Completion``. Alles Weitere — Schleife, Budget, Werkzeugausführung — gehört dem Harness.
Diese Trennung ist die Voraussetzung dafür, dass der Harness beim Benchmark die
Kontrollvariable bleibt und nur das Modell wechselt.
"""

from __future__ import annotations

from typing import Any, Protocol

from ..messages import Completion, Message


class ProviderError(RuntimeError):
    """Der Modellaufruf ist endgültig fehlgeschlagen."""


class Provider(Protocol):
    model_id: str

    async def complete(
        self,
        messages: list[Message],
        *,
        tools: list[dict[str, Any]] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> Completion: ...

    async def aclose(self) -> None: ...
