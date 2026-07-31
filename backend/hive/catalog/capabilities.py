"""Ableitung der Schwarm-Rollentauglichkeit aus den Katalogfeldern.

Das ist die zentrale Domänenlogik von M0: Aus ``supported_parameters`` und
``architecture.input_modalities`` folgt, für welche Rolle ein Modell überhaupt in Frage kommt.

Die Rollenteilung des Schwarms folgt einer realen Fähigkeitsgrenze, nicht einem Entwurfswunsch:
Viele günstige Modelle beherrschen kein Tool-Calling. Statt sie auszuschließen, planen sie als
Scouts in Text — ausführen mit Werkzeugen übernehmen Worker.
"""

from __future__ import annotations

from enum import StrEnum

from .models import OpenRouterModel

# Werte in ``supported_parameters``, die Tool-Calling anzeigen.
TOOL_PARAMETERS = frozenset({"tools", "tool_choice"})
STRUCTURED_OUTPUT_PARAMETERS = frozenset({"response_format", "structured_outputs"})
IMAGE_MODALITIES = frozenset({"image"})


class Role(StrEnum):
    SCOUT = "scout"
    WORKER = "worker"
    INSPECTOR = "inspector"
    QUEEN = "queen"


class Capabilities:
    """Abgeleitete Fähigkeiten eines Modells."""

    __slots__ = ("is_free", "supports_structured_output", "supports_tools", "supports_vision")

    def __init__(
        self,
        *,
        supports_tools: bool,
        supports_vision: bool,
        supports_structured_output: bool,
        is_free: bool,
    ) -> None:
        self.supports_tools = supports_tools
        self.supports_vision = supports_vision
        self.supports_structured_output = supports_structured_output
        self.is_free = is_free

    @property
    def roles(self) -> list[Role]:
        """Rollen, für die das Modell technisch geeignet ist.

        Scout ist immer dabei: Scouts liefern Textpläne und brauchen keine Werkzeuge.
        Worker und Queen greifen zu Werkzeugen, Inspectors müssen Screenshots sehen können.
        Eignung heißt hier ausschließlich *technisch möglich* — ob ein Modell für eine Rolle
        auch stark genug ist, beantwortet erst der Benchmark.
        """
        roles = [Role.SCOUT]
        if self.supports_tools:
            roles.extend((Role.WORKER, Role.QUEEN))
        if self.supports_vision:
            roles.append(Role.INSPECTOR)
        return roles

    @property
    def ineligible_reason(self) -> str | None:
        """Warum das Modell keinen vollen Schwarm-Lauf fahren kann — oder ``None``.

        Wird im Dashboard sichtbar angezeigt, statt solche Modelle stillschweigend
        wegzufiltern: Wer wissen will, warum ein Modell fehlt, soll es sehen können.
        """
        if not self.supports_tools:
            return "Kein Tool-Calling — nur als Scout einsetzbar"
        return None


def derive_capabilities(model: OpenRouterModel) -> Capabilities:
    params = {p.lower() for p in model.supported_parameters}
    modalities = {m.lower() for m in model.architecture.input_modalities}
    return Capabilities(
        supports_tools=bool(params & TOOL_PARAMETERS),
        supports_vision=bool(modalities & IMAGE_MODALITIES),
        supports_structured_output=bool(params & STRUCTURED_OUTPUT_PARAMETERS),
        is_free=model.pricing.is_free,
    )
