"""Werkzeug-Registry: JSON-Schema aus Typannotationen.

Der Ansatz ist bewusst schmal — kein Framework, sondern eine Ableitung des Schemas aus der
Signatur. Damit gibt es genau eine Stelle, an der ein Werkzeug definiert ist: die Funktion.

Zentrale Eigenschaft: **Werkzeugfehler sind Rückmeldung, kein Absturz.** Ein halluzinierter
Werkzeugname oder ungültige Argumente werden dem Modell als Text zurückgegeben, damit es sich
korrigieren kann. Nur so übersteht der Loop schwächere Modelle — und die sollen im Schwarm
gerade die Mehrheit stellen.
"""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from typing import Any

from pydantic import BaseModel, ValidationError, create_model

ToolHandler = Callable[..., Awaitable[str]]


class ToolError(Exception):
    """Fachlicher Fehler eines Werkzeugs — wird dem Modell mitgeteilt, bricht den Lauf nicht ab."""


class ToolSpec(BaseModel):
    """Ein registriertes Werkzeug samt abgeleitetem Parameterschema."""

    model_config = {"arbitrary_types_allowed": True}

    name: str
    description: str
    parameters: dict[str, Any]
    handler: ToolHandler
    argument_model: type[BaseModel]

    def as_openai_schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


def _clean_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Entfernt Pydantic-Beiwerk, das für Modelle nur Rauschen ist.

    Die von ``model_json_schema`` erzeugten ``title``-Felder blähen den Prompt auf, ohne
    Information zu tragen — bei vielen Werkzeugen summiert sich das über jeden Aufruf.
    """
    schema.pop("title", None)
    for prop in schema.get("properties", {}).values():
        if isinstance(prop, dict):
            prop.pop("title", None)
    return schema


def tool_from_function(fn: ToolHandler, *, name: str | None = None) -> ToolSpec:
    """Baut eine ``ToolSpec`` aus einer async-Funktion mit Typannotationen.

    Der Docstring wird zur Beschreibung — das Modell liest ihn, also ist er kein Kommentar,
    sondern Teil der Schnittstelle.
    """
    signature = inspect.signature(fn)
    fields: dict[str, Any] = {}
    for param_name, param in signature.parameters.items():
        if param.annotation is inspect.Parameter.empty:
            raise TypeError(f"Werkzeug {fn.__name__}: Parameter '{param_name}' ohne Typannotation")
        default = ... if param.default is inspect.Parameter.empty else param.default
        fields[param_name] = (param.annotation, default)

    argument_model = create_model(f"{fn.__name__}_args", **fields)
    description = inspect.getdoc(fn) or ""
    if not description:
        raise ValueError(f"Werkzeug {fn.__name__} braucht einen Docstring — das Modell liest ihn")

    return ToolSpec(
        name=name or fn.__name__,
        description=description,
        parameters=_clean_schema(argument_model.model_json_schema()),
        handler=fn,
        argument_model=argument_model,
    )


class ToolRegistry:
    """Sammlung verfügbarer Werkzeuge für einen Agenten."""

    def __init__(self, specs: list[ToolSpec] | None = None) -> None:
        self._specs: dict[str, ToolSpec] = {}
        for spec in specs or []:
            self.register(spec)

    def register(self, spec: ToolSpec) -> None:
        if spec.name in self._specs:
            raise ValueError(f"Werkzeug '{spec.name}' ist bereits registriert")
        self._specs[spec.name] = spec

    def add_function(self, fn: ToolHandler, *, name: str | None = None) -> None:
        self.register(tool_from_function(fn, name=name))

    @property
    def names(self) -> list[str]:
        return sorted(self._specs)

    def subset(self, names: list[str]) -> ToolRegistry:
        """Teilmenge für eine Rolle — Scouts bekommen nur lesende Werkzeuge."""
        missing = [n for n in names if n not in self._specs]
        if missing:
            raise KeyError(f"Unbekannte Werkzeuge: {', '.join(missing)}")
        return ToolRegistry([self._specs[n] for n in names])

    def as_openai_schema(self) -> list[dict[str, Any]]:
        return [self._specs[name].as_openai_schema() for name in self.names]

    async def invoke(self, name: str, arguments: dict[str, Any]) -> tuple[str, bool]:
        """Führt ein Werkzeug aus.

        Gibt ``(ergebnis, erfolgreich)`` zurück. Bei Fehlern steht im Ergebnis eine für das
        Modell lesbare Erklärung — inklusive der Liste verfügbarer Werkzeuge, wenn der Name
        nicht existiert.
        """
        spec = self._specs.get(name)
        if spec is None:
            return (
                f"Fehler: Werkzeug '{name}' existiert nicht. Verfügbar: {', '.join(self.names)}",
                False,
            )

        try:
            validated = spec.argument_model.model_validate(arguments)
        except ValidationError as exc:
            return (f"Fehler: ungültige Argumente für '{name}'.\n{exc}", False)

        try:
            result = await spec.handler(**validated.model_dump())
        except ToolError as exc:
            return (f"Fehler: {exc}", False)
        except Exception as exc:
            return (f"Fehler bei '{name}': {type(exc).__name__}: {exc}", False)

        return (result, True)
