"""Command line: ``hive catalog``, ``hive template``, ``hive run``, ``hive openapi``."""

from __future__ import annotations

import asyncio
import json

import typer

from .catalog import CatalogFetchError, CatalogService, CatalogUnavailableError, to_summary
from .config import get_settings
from .sandbox.docker_sandbox import NetworkMode
from .templates.store import TemplateStore

app = typer.Typer(no_args_is_help=True, add_completion=False, help="Agent Hive")
catalog_app = typer.Typer(no_args_is_help=True, help="Manage the model catalog")
app.add_typer(catalog_app, name="catalog")


def _service() -> CatalogService:
    from .api.deps import get_catalog_service

    return get_catalog_service()


@catalog_app.command("sync")
def sync() -> None:
    """Fetch the catalog from OpenRouter and store it as a new snapshot."""
    settings = get_settings()
    typer.echo(f"Fetching {settings.catalog_source} …")
    try:
        snapshot = asyncio.run(_service().sync(timeout=settings.catalog_timeout_seconds))
    except CatalogFetchError as exc:
        typer.secho(f"Failed: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1) from exc

    summaries = [to_summary(m) for m in snapshot.models]
    tools = sum(1 for s in summaries if s.supports_tools)
    vision = sum(1 for s in summaries if s.supports_vision)

    typer.secho(f"Snapshot {snapshot.snapshot_id} stored", fg=typer.colors.GREEN)
    typer.echo(f"  models total  : {len(summaries)}")
    typer.echo(f"  with tools    : {tools}   (worker/queen capable)")
    typer.echo(f"  with vision   : {vision}   (inspector capable)")
    typer.echo(f"  location      : {settings.catalog_dir}")


@catalog_app.command("show")
def show(
    limit: int = typer.Option(20, help="Number of rows"),
    tools_only: bool = typer.Option(False, "--tools-only", help="Only tool-capable models"),
    as_json: bool = typer.Option(False, "--json", help="Raw JSON output"),
) -> None:
    """Show the current catalog state, sorted by blended price."""
    try:
        state = _service().current()
    except CatalogUnavailableError as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(1) from exc

    summaries = [to_summary(m) for m in state.models]
    if tools_only:
        summaries = [s for s in summaries if s.supports_tools]
    summaries.sort(key=lambda s: (s.blended_usd_per_mtok is None, s.blended_usd_per_mtok or 0.0))
    selected = summaries[:limit]

    if as_json:
        typer.echo(json.dumps([s.model_dump() for s in selected], indent=2, ensure_ascii=False))
        return

    origin = "bundled fixture" if state.is_fixture else "snapshot"
    typer.echo(f"{origin} {state.snapshot.snapshot_id} — {len(summaries)} models\n")
    typer.echo(f"{'MODEL':<48} {'$/MTok':>9}  {'CONTEXT':>9}  ROLES")
    for summary in selected:
        blended = summary.blended_usd_per_mtok
        price = "?" if blended is None else f"{blended:.3f}"
        context = "?" if summary.context_length is None else f"{summary.context_length:,}"
        roles = ",".join(r.value for r in summary.roles)
        typer.echo(f"{summary.id[:48]:<48} {price:>9}  {context:>9}  {roles}")


def _template_store() -> TemplateStore:
    return TemplateStore(get_settings().templates_dir)


@app.command("run")
def run(
    goal: str = typer.Option("", "--goal", "-g", help="Free-form task description"),
    template_name: str = typer.Option("", "--template", "-t", help="Template instead of a goal"),
    model: str = typer.Option("", "--model", "-m", help="Model id from the catalog"),
    provider_kind: str = typer.Option(
        "openrouter", "--provider", help="openrouter | mock (recorded example run)"
    ),
    network: str = typer.Option(
        "", "--network", help="none | bridge | internal (only without a template)"
    ),
    max_iterations: int = typer.Option(20, help="Iteration limit (only without a template)"),
    max_usd: float = typer.Option(5.0, help="Cost ceiling in USD (only without a template)"),
    read_only: bool = typer.Option(False, "--read-only", help="Read-only tools (scout)"),
    skip_checks: bool = typer.Option(False, "--skip-checks", help="Do not run checks"),
    verbose: bool = typer.Option(False, "-v", "--verbose", help="Print every event"),
) -> None:
    """Point an agent at a goal or template inside a Docker sandbox."""
    from decimal import Decimal

    from .demo import DEMO_GOAL, build_demo_provider, build_template_demo_provider
    from .demo_voxel import build_voxel_demo_provider
    from .harness.budget import BudgetLimits
    from .harness.providers.base import Provider, ProviderError
    from .harness.providers.openrouter import OpenRouterProvider
    from .harness.runner import RunConfig, config_from_template, execute_run
    from .sandbox.docker_sandbox import SandboxError, SandboxLimits
    from .templates.store import TemplateError

    settings = get_settings()
    store = _template_store()
    provider: Provider

    template = None
    if template_name:
        try:
            template = store.load(template_name)
        except TemplateError as exc:
            typer.secho(str(exc), fg=typer.colors.RED, err=True)
            raise typer.Exit(2) from exc

    if provider_kind == "mock":
        # Pick the recorded solution matching the template so the whole check chain can be
        # exercised without an API key.
        if template_name == "minecraft-clone":
            demo = build_voxel_demo_provider()
        elif template:
            demo = build_template_demo_provider()
        else:
            demo = build_demo_provider()
        provider = demo
        model = model or demo.model_id
        goal = goal or DEMO_GOAL
    else:
        if not model:
            typer.secho("--model is required", fg=typer.colors.RED, err=True)
            raise typer.Exit(2)
        if not goal and not template:
            typer.secho("--goal or --template is required", fg=typer.colors.RED, err=True)
            raise typer.Exit(2)
        try:
            provider = OpenRouterProvider(model, api_key=settings.openrouter_api_key)
        except ProviderError as exc:
            typer.secho(str(exc), fg=typer.colors.RED, err=True)
            raise typer.Exit(2) from exc

    if template is not None:
        config = config_from_template(template, model_id=model)
    else:
        raw = network or settings.sandbox_network
        if raw not in ("none", "bridge", "internal"):
            typer.secho(
                f"Unknown network mode '{raw}' — allowed: none, bridge, internal",
                fg=typer.colors.RED,
                err=True,
            )
            raise typer.Exit(2)
        chosen: NetworkMode = raw  # type: ignore[assignment]

        config = RunConfig(
            model_id=model,
            goal=goal,
            budget=BudgetLimits(max_iterations=max_iterations, max_cost_usd=Decimal(str(max_usd))),
            sandbox=SandboxLimits(
                image=settings.sandbox_image,
                memory_mb=settings.sandbox_memory_mb,
                cpus=settings.sandbox_cpus,
                network=chosen,
            ),
            read_only=read_only,
        )

    typer.echo(f"Model    : {model}")
    if template:
        typer.echo(f"Template : {template.ref}  (hash {template.content_hash})")
    typer.echo(f"Network  : {config.sandbox.network}")
    typer.echo(f"Goal     : {config.goal[:160]}{'…' if len(config.goal) > 160 else ''}\n")

    screenshots = settings.screenshots_dir
    try:
        outcome = asyncio.run(
            execute_run(
                config,
                provider=provider,
                catalog=_service(),
                templates=None if skip_checks else store,
                screenshot_dir=screenshots,
            )
        )
    except SandboxError as exc:
        typer.secho(f"Sandbox: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1) from exc

    if verbose:
        for event in outcome.events:
            typer.echo(f"  [{event.sequence:>3}] {event.type.value}  {event.payload}")
        typer.echo("")

    result = outcome.result
    colour = typer.colors.GREEN if result.succeeded else typer.colors.YELLOW
    typer.secho(f"Agent: {result.stop_reason.value} — {result.detail}", fg=colour)
    if result.budget:
        typer.echo(f"Consumed: {result.budget.format()}")
    if not outcome.pricing_known and provider_kind != "mock":
        typer.secho(
            "Note: no catalog prices known for this model — the cost figure is not reliable.",
            fg=typer.colors.YELLOW,
        )

    if outcome.checks is not None:
        verdict = "passed" if outcome.checks.passed else "failed"
        check_colour = typer.colors.GREEN if outcome.checks.passed else typer.colors.RED
        typer.secho(f"\nChecks: {verdict}", fg=check_colour)
        typer.echo(outcome.checks.format())
        if outcome.checks.screenshots:
            typer.echo(f"  stored in {screenshots}")

    if outcome.workspace:
        typer.echo(f"\nWorkspace:\n{outcome.workspace}")
    if result.final_message:
        typer.echo(f"\nAnswer:\n{result.final_message}")

    passed = result.succeeded and (outcome.checks is None or outcome.checks.passed)
    raise typer.Exit(0 if passed else 1)


template_app = typer.Typer(no_args_is_help=True, help="Task templates")
app.add_typer(template_app, name="template")


@template_app.command("list")
def template_list() -> None:
    """List all templates."""
    from .templates.store import TemplateError

    store = _template_store()
    names = store.names()
    if not names:
        typer.secho(f"No templates under {store.root}", fg=typer.colors.YELLOW)
        raise typer.Exit(1)

    typer.echo(f"{'TEMPLATE':<24} {'VER':>4}  {'HASH':<18} CHECKS")
    for name in names:
        try:
            template = store.load(name)
        except TemplateError as exc:
            typer.secho(f"{name:<24}  — broken: {exc}", fg=typer.colors.RED)
            continue
        checks = ", ".join(c.name for c in template.checks) or "none"
        typer.echo(
            f"{template.name:<24} {template.version:>4}  {template.content_hash:<18} {checks}"
        )


@template_app.command("show")
def template_show(name: str) -> None:
    """Show one template in detail."""
    from .templates.store import TemplateError

    try:
        template = _template_store().load(name)
    except TemplateError as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(1) from exc

    typer.echo(json.dumps(template.model_dump(mode="json"), indent=2, ensure_ascii=False))


@app.command("openapi")
def openapi(out: str = typer.Option("../openapi.json", help="Target file")) -> None:
    """Export the OpenAPI schema.

    The basis for the frontend's TypeScript types: pydantic stays the single schema source,
    the frontend generates from it (``npm run types``).
    """
    from pathlib import Path

    from .api.app import create_app

    schema = create_app().openapi()
    path = Path(out)
    path.write_text(json.dumps(schema, indent=2, ensure_ascii=False), encoding="utf-8")
    typer.secho(f"Schema written: {path.resolve()}", fg=typer.colors.GREEN)


if __name__ == "__main__":
    app()
