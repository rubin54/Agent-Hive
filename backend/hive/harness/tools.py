"""Tool registry: JSON schema derived from type annotations.

Deliberately narrow — no framework, just schema derivation from the signature. That leaves
exactly one place where a tool is defined: the function itself.

Central property: **tool failures are feedback, not crashes.** A hallucinated tool name or
invalid arguments are handed back to the model as text so it can correct itself. That is the
only way the loop survives weaker models — and those are meant to be the majority in a swarm.
"""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from typing import Any

from pydantic import BaseModel, ValidationError, create_model

ToolHandler = Callable[..., Awaitable[str]]


class ToolError(Exception):
    """A tool-level failure — reported to the model, does not abort the run."""


class ToolSpec(BaseModel):
    """A registered tool with its derived parameter schema."""

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
    """Strip pydantic noise that carries no information for a model.

    The ``title`` fields produced by ``model_json_schema`` inflate the prompt without adding
    meaning — across many tools that adds up on every single call.
    """
    schema.pop("title", None)
    for prop in schema.get("properties", {}).values():
        if isinstance(prop, dict):
            prop.pop("title", None)
    return schema


def tool_from_function(fn: ToolHandler, *, name: str | None = None) -> ToolSpec:
    """Build a ``ToolSpec`` from an async function with type annotations.

    The docstring becomes the description — the model reads it, so it is part of the
    interface rather than a comment.
    """
    signature = inspect.signature(fn)
    fields: dict[str, Any] = {}
    for param_name, param in signature.parameters.items():
        if param.annotation is inspect.Parameter.empty:
            raise TypeError(f"Tool {fn.__name__}: parameter '{param_name}' has no type annotation")
        default = ... if param.default is inspect.Parameter.empty else param.default
        fields[param_name] = (param.annotation, default)

    argument_model = create_model(f"{fn.__name__}_args", **fields)
    description = inspect.getdoc(fn) or ""
    if not description:
        raise ValueError(f"Tool {fn.__name__} needs a docstring — the model reads it")

    return ToolSpec(
        name=name or fn.__name__,
        description=description,
        parameters=_clean_schema(argument_model.model_json_schema()),
        handler=fn,
        argument_model=argument_model,
    )


class ToolRegistry:
    """The set of tools available to an agent."""

    def __init__(self, specs: list[ToolSpec] | None = None) -> None:
        self._specs: dict[str, ToolSpec] = {}
        for spec in specs or []:
            self.register(spec)

    def register(self, spec: ToolSpec) -> None:
        if spec.name in self._specs:
            raise ValueError(f"Tool '{spec.name}' is already registered")
        self._specs[spec.name] = spec

    def add_function(self, fn: ToolHandler, *, name: str | None = None) -> None:
        self.register(tool_from_function(fn, name=name))

    @property
    def names(self) -> list[str]:
        return sorted(self._specs)

    def subset(self, names: list[str]) -> ToolRegistry:
        """Subset for a role — scouts only get read-only tools."""
        missing = [n for n in names if n not in self._specs]
        if missing:
            raise KeyError(f"Unknown tools: {', '.join(missing)}")
        return ToolRegistry([self._specs[n] for n in names])

    def as_openai_schema(self) -> list[dict[str, Any]]:
        return [self._specs[name].as_openai_schema() for name in self.names]

    async def invoke(self, name: str, arguments: dict[str, Any]) -> tuple[str, bool]:
        """Execute a tool.

        Returns ``(result, succeeded)``. On failure the result carries an explanation the
        model can act on — including the list of available tools when the name is unknown.
        """
        spec = self._specs.get(name)
        if spec is None:
            return (
                f"Error: tool '{name}' does not exist. Available: {', '.join(self.names)}",
                False,
            )

        try:
            validated = spec.argument_model.model_validate(arguments)
        except ValidationError as exc:
            return (f"Error: invalid arguments for '{name}'.\n{exc}", False)

        try:
            result = await spec.handler(**validated.model_dump())
        except ToolError as exc:
            return (f"Error: {exc}", False)
        except Exception as exc:
            # A tool must never take down the whole run — the model gets the error as text.
            return (f"Error in '{name}': {type(exc).__name__}: {exc}", False)

        return (result, True)
