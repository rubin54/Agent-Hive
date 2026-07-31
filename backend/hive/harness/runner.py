"""Assembly of a single run.

Ties together catalog (prices), template, provider, sandbox, tools, budget, agent and
evaluation. From M5 the swarm engine calls the same assembly per role — the difference is
then only model, tool set and budget share, never the loop.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Literal

from ..catalog.models import Pricing
from ..catalog.service import CatalogService, CatalogUnavailableError
from ..checks.runner import CheckReport, run_checks
from ..sandbox.docker_sandbox import DockerSandbox, SandboxLimits
from ..sandbox.tools import build_tools
from ..templates.models import Template
from ..templates.store import TemplateStore
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
    #: Set when the run originates from a template. Its checks then run afterwards.
    template: Template | None = None
    agent_internet: bool = False


@dataclass(slots=True)
class RunOutcome:
    run_id: str
    config: RunConfig
    result: AgentResult
    events: list[Event]
    workspace: str
    pricing_known: bool
    checks: CheckReport | None = None

    @property
    def template_ref(self) -> str | None:
        return self.config.template.ref if self.config.template else None


def config_from_template(
    template: Template, *, model_id: str, image_override: str | None = None
) -> RunConfig:
    """Translate a template into a run configuration.

    Everything that influences the comparison — prompt, budget, network mode, image — comes
    from the template and not from the command line. Otherwise the control variable would be
    adjustable by accident.
    """
    return RunConfig(
        model_id=model_id,
        goal=template.prompt,
        budget=BudgetLimits(
            max_iterations=template.budget.max_iterations,
            max_tokens=template.budget.max_tokens,
            max_wall_clock_seconds=template.budget.max_wall_clock_seconds,
            max_cost_usd=template.budget.max_cost_usd,
        ),
        sandbox=SandboxLimits(
            image=image_override or template.workspace.image,
            network=template.workspace.network,
        ),
        template=template,
        agent_internet=template.workspace.agent_internet,
    )


def pricing_for(service: CatalogService, model_id: str) -> Pricing | None:
    """Catalog prices of a model, if known.

    Without prices the cost axis stays at zero. That is more honest than an estimate — and it
    makes the run unusable for the benchmark, which has to stay visible.
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
    templates: TemplateStore | None = None,
    screenshot_dir: Path | None = None,
    run_id: str | None = None,
) -> RunOutcome:
    """Execute a run in a fresh sandbox and tear it down afterwards."""
    identifier = run_id or uuid.uuid4().hex[:12]
    sink = MemorySink(run_id=identifier)

    pricing = pricing_for(catalog, config.model_id) if catalog else None
    tracker = BudgetTracker(limits=config.budget, pricing=pricing)

    sandbox = await DockerSandbox.create(config.sandbox)
    checks: CheckReport | None = None
    try:
        if config.template is not None and templates is not None:
            for path, content in templates.starter_files(config.template):
                await sandbox.write_file(path, content)

        # Internet access for the agent phase only. The check phase must not see it —
        # otherwise an application could still pull resources at check time that would not
        # be reproducible in the result.
        agent_network: str | None = None
        if config.agent_internet:
            agent_network = await sandbox.attach_network("bridge")

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
        finally:
            if agent_network:
                await sandbox.detach_network(agent_network)

        if config.template is not None and templates is not None:
            checks = await run_checks(
                config.template, sandbox, templates, screenshot_dir=screenshot_dir
            )

        # Capture the file tree before teardown — after ``destroy`` it is gone.
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
        checks=checks,
    )


ProviderKind = Literal["openrouter", "mock"]
UNKNOWN_COST = Decimal(0)
