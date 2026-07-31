"""Derives swarm role eligibility from catalog fields.

This is the core domain logic of M0: ``supported_parameters`` and
``architecture.input_modalities`` determine which role a model can fill at all.

The swarm's division of labour follows a real capability boundary, not a design preference:
many cheap models cannot call tools. Rather than excluding them, they plan as scouts in text —
workers do the execution with tools.
"""

from __future__ import annotations

from enum import StrEnum

from .models import OpenRouterModel

# Values in ``supported_parameters`` that indicate tool calling.
TOOL_PARAMETERS = frozenset({"tools", "tool_choice"})
STRUCTURED_OUTPUT_PARAMETERS = frozenset({"response_format", "structured_outputs"})
IMAGE_MODALITIES = frozenset({"image"})


class Role(StrEnum):
    SCOUT = "scout"
    WORKER = "worker"
    INSPECTOR = "inspector"
    QUEEN = "queen"


class Capabilities:
    """Derived capabilities of a model."""

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
        """Roles the model is technically eligible for.

        Scout is always included: scouts produce text plans and need no tools. Workers and
        queens reach for tools, inspectors must be able to see screenshots. Eligibility here
        means *technically possible* only — whether a model is also strong enough for a role
        is what the benchmark answers.
        """
        roles = [Role.SCOUT]
        if self.supports_tools:
            roles.extend((Role.WORKER, Role.QUEEN))
        if self.supports_vision:
            roles.append(Role.INSPECTOR)
        return roles

    @property
    def ineligible_reason(self) -> str | None:
        """Why the model cannot run a full swarm — or ``None``.

        Shown in the dashboard rather than filtering such models out silently: anyone
        wondering why a model is missing should be able to see it.
        """
        if not self.supports_tools:
            return "No tool calling — usable as scout only"
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
