"""Kommandozeile: ``hive catalog sync``, ``hive catalog show``."""

from __future__ import annotations

import asyncio
import json

import typer

from .catalog import CatalogFetchError, CatalogService, CatalogUnavailableError, to_summary
from .config import get_settings

app = typer.Typer(no_args_is_help=True, add_completion=False, help="Agent Hive")
catalog_app = typer.Typer(no_args_is_help=True, help="Modellkatalog verwalten")
app.add_typer(catalog_app, name="catalog")


def _service() -> CatalogService:
    from .api.deps import get_catalog_service

    return get_catalog_service()


@catalog_app.command("sync")
def sync() -> None:
    """Katalog von OpenRouter laden und als neuen Snapshot ablegen."""
    settings = get_settings()
    typer.echo(f"Lade {settings.catalog_source} …")
    try:
        snapshot = asyncio.run(_service().sync(timeout=settings.catalog_timeout_seconds))
    except CatalogFetchError as exc:
        typer.secho(f"Fehlgeschlagen: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1) from exc

    summaries = [to_summary(m) for m in snapshot.models]
    tools = sum(1 for s in summaries if s.supports_tools)
    vision = sum(1 for s in summaries if s.supports_vision)

    typer.secho(f"Snapshot {snapshot.snapshot_id} gespeichert", fg=typer.colors.GREEN)
    typer.echo(f"  Modelle gesamt : {len(summaries)}")
    typer.echo(f"  mit Tools      : {tools}   (Worker/Queen-tauglich)")
    typer.echo(f"  mit Vision     : {vision}   (Inspector-tauglich)")
    typer.echo(f"  Ablage         : {settings.catalog_dir}")


@catalog_app.command("show")
def show(
    limit: int = typer.Option(20, help="Anzahl Zeilen"),
    tools_only: bool = typer.Option(False, "--tools-only", help="Nur Tool-fähige Modelle"),
    as_json: bool = typer.Option(False, "--json", help="Rohausgabe als JSON"),
) -> None:
    """Den aktuellen Katalogstand anzeigen, sortiert nach Mischpreis."""
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

    origin = "mitgelieferte Fixture" if state.is_fixture else "Snapshot"
    typer.echo(f"{origin} {state.snapshot.snapshot_id} — {len(summaries)} Modelle\n")
    typer.echo(f"{'MODELL':<48} {'$/MTok':>9}  {'KONTEXT':>9}  ROLLEN")
    for summary in selected:
        blended = summary.blended_usd_per_mtok
        price = "?" if blended is None else f"{blended:.3f}"
        context = "?" if summary.context_length is None else f"{summary.context_length:,}"
        roles = ",".join(r.value for r in summary.roles)
        typer.echo(f"{summary.id[:48]:<48} {price:>9}  {context:>9}  {roles}")


@app.command("run")
def run(
    goal: str = typer.Option("", "--goal", "-g", help="Aufgabenstellung für den Agenten"),
    model: str = typer.Option("", "--model", "-m", help="Modell-ID aus dem Katalog"),
    provider_kind: str = typer.Option(
        "openrouter", "--provider", help="openrouter | mock (aufgezeichneter Beispiellauf)"
    ),
    network: str = typer.Option(
        "", "--network", help="none | bridge — bridge erlaubt Paketinstallation"
    ),
    max_iterations: int = typer.Option(20, help="Iterationslimit"),
    max_usd: float = typer.Option(5.0, help="Kostenobergrenze in USD (Notbremse)"),
    read_only: bool = typer.Option(False, "--read-only", help="Nur lesende Werkzeuge (Scout)"),
    verbose: bool = typer.Option(False, "-v", "--verbose", help="Jedes Ereignis ausgeben"),
) -> None:
    """Einen Agenten in einer Docker-Sandbox auf ein Ziel ansetzen."""
    from decimal import Decimal

    from .demo import DEMO_GOAL, build_demo_provider
    from .harness.budget import BudgetLimits
    from .harness.providers.base import Provider, ProviderError
    from .harness.providers.openrouter import OpenRouterProvider
    from .harness.runner import RunConfig, execute_run
    from .sandbox.docker_sandbox import SandboxError, SandboxLimits

    settings = get_settings()
    provider: Provider

    if provider_kind == "mock":
        demo = build_demo_provider()
        provider = demo
        model = model or demo.model_id
        goal = goal or DEMO_GOAL
    else:
        if not model:
            typer.secho("--model wird gebraucht", fg=typer.colors.RED, err=True)
            raise typer.Exit(2)
        if not goal:
            typer.secho("--goal wird gebraucht", fg=typer.colors.RED, err=True)
            raise typer.Exit(2)
        try:
            provider = OpenRouterProvider(model, api_key=settings.openrouter_api_key)
        except ProviderError as exc:
            typer.secho(str(exc), fg=typer.colors.RED, err=True)
            raise typer.Exit(2) from exc

    chosen_network = network or settings.sandbox_network
    config = RunConfig(
        model_id=model,
        goal=goal,
        budget=BudgetLimits(max_iterations=max_iterations, max_cost_usd=Decimal(str(max_usd))),
        sandbox=SandboxLimits(
            image=settings.sandbox_image,
            memory_mb=settings.sandbox_memory_mb,
            cpus=settings.sandbox_cpus,
            network="bridge" if chosen_network == "bridge" else "none",
        ),
        read_only=read_only,
    )

    typer.echo(f"Modell   : {model}")
    typer.echo(f"Netzwerk : {config.sandbox.network}")
    typer.echo(f"Ziel     : {goal}\n")

    try:
        outcome = asyncio.run(execute_run(config, provider=provider, catalog=_service()))
    except SandboxError as exc:
        typer.secho(f"Sandbox: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1) from exc

    if verbose:
        for event in outcome.events:
            typer.echo(f"  [{event.sequence:>3}] {event.type.value}  {event.payload}")
        typer.echo("")

    result = outcome.result
    colour = typer.colors.GREEN if result.succeeded else typer.colors.YELLOW
    typer.secho(f"Ende: {result.stop_reason.value} — {result.detail}", fg=colour)
    if result.budget:
        typer.echo(f"Verbrauch: {result.budget.format()}")
    if not outcome.pricing_known and provider_kind != "mock":
        typer.secho(
            "Hinweis: Für dieses Modell sind keine Katalogpreise bekannt — "
            "die Kostenangabe ist deshalb nicht belastbar.",
            fg=typer.colors.YELLOW,
        )
    if outcome.workspace:
        typer.echo(f"\nArbeitsbereich:\n{outcome.workspace}")
    if result.final_message:
        typer.echo(f"\nAntwort:\n{result.final_message}")

    raise typer.Exit(0 if result.succeeded else 1)


@app.command("openapi")
def openapi(out: str = typer.Option("../openapi.json", help="Zieldatei")) -> None:
    """OpenAPI-Schema exportieren.

    Grundlage für die TypeScript-Typen des Frontends: Pydantic bleibt die einzige
    Schema-Quelle, das Frontend generiert daraus (``npm run types``).
    """
    from pathlib import Path

    from .api.app import create_app

    schema = create_app().openapi()
    path = Path(out)
    path.write_text(json.dumps(schema, indent=2, ensure_ascii=False), encoding="utf-8")
    typer.secho(f"Schema geschrieben: {path.resolve()}", fg=typer.colors.GREEN)


if __name__ == "__main__":
    app()
