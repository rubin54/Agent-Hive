"""Zusammenbau eines einzelnen Laufs.

Bindet Katalog (Preise), Provider, Sandbox, Werkzeuge, Budget und Agent zusammen. Ab M5 ruft
die Schwarm-Engine denselben Aufbau je Rolle auf — der Unterschied liegt dann nur in Modell,
Werkzeugmenge und Budgetanteil, nicht im Loop.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Literal

from ..catalog.models import Pricing
from ..catalog.service import CatalogService, CatalogUnavailableError
from ..sandbox.docker_sandbox import DockerSandbox, SandboxLimits
from ..sandbox.tools import build_tools
from .agent import DEFAULT_SYSTEM_PROMPT, Agent, AgentResult
from .budget import BudgetLimits, BudgetTracker
from .events import Event, MemorySink
from .providers.base import Provider


@dataclass(slots=True)
class RunConfig:
    model_id: str
    goal: str
    budget: BudgetLimits = field(default_factory=BudgetLimits)
    sandbox: SandboxLimits = field(default_factory=SandboxLimits)
    read_only: bool = False
    system_prompt: str = DEFAULT_SYSTEM_PROMPT
    temperature: float | None = None


@dataclass(slots=True)
class RunOutcome:
    run_id: str
    config: RunConfig
    result: AgentResult
    events: list[Event]
    workspace: str
    pricing_known: bool


def pricing_for(service: CatalogService, model_id: str) -> Pricing | None:
    """Katalogpreise eines Modells, falls bekannt.

    Ohne Preise bleibt die Kostenachse bei null. Das ist ehrlicher als eine geschätzte Zahl —
    und der Lauf ist damit für den Benchmark unbrauchbar, was sichtbar bleiben muss.
    """
    try:
        state = service.current()
    except CatalogUnavailableError:
        return None
    for model in state.models:
        if model.id == model_id:
            return model.pricing
    return None


async def execute_run(
    config: RunConfig,
    *,
    provider: Provider,
    catalog: CatalogService | None = None,
    run_id: str | None = None,
) -> RunOutcome:
    """Führt einen Lauf in einer frischen Sandbox aus und räumt sie danach ab."""
    identifier = run_id or uuid.uuid4().hex[:12]
    sink = MemorySink(run_id=identifier)

    pricing = pricing_for(catalog, config.model_id) if catalog else None
    tracker = BudgetTracker(limits=config.budget, pricing=pricing)

    sandbox = await DockerSandbox.create(config.sandbox)
    try:
        tools = build_tools(sandbox, read_only=config.read_only)
        agent = Agent(
            provider=provider,
            tools=tools,
            budget=tracker,
            sink=sink,
            system_prompt=config.system_prompt,
            temperature=config.temperature,
        )
        result = await agent.run(config.goal)

        # Der Dateibaum wird vor dem Abbau festgehalten — nach `destroy` ist er weg, und
        # ab M3 hängt die Bewertung genau daran.
        listing = await sandbox.exec(
            "find . -maxdepth 3 -not -path '*/node_modules/*' -not -path '*/.git/*' "
            "-not -name node_modules -not -name .git | sort | head -100"
        )
        workspace = listing.stdout.strip()
    finally:
        await sandbox.destroy()

    return RunOutcome(
        run_id=identifier,
        config=config,
        result=result,
        events=sink.events,
        workspace=workspace,
        pricing_known=pricing is not None
        and pricing.prompt is not None
        and pricing.completion is not None,
    )


ProviderKind = Literal["openrouter", "mock"]
