"""Starting, tracking and reading runs.

Sits above the harness: turns a request into a configuration, launches the run as a
background task, keeps the journal up to date and exposes the live stream.

Runs execute inside the API process. For a single-user tool that is the right trade — a
durable job queue would be considerable machinery without portfolio gain. The consequence is
documented and visible: a server restart marks in-flight runs as failed on next read rather
than pretending they still run.
"""

from __future__ import annotations

import asyncio
import contextlib
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from ..catalog.service import CatalogService
from ..harness.events import Event
from ..harness.providers.base import Provider, ProviderError
from ..harness.providers.openrouter import OpenRouterProvider
from ..harness.runner import RunConfig, RunOutcome, config_from_template, execute_run
from ..journal.registry import RunRegistry
from ..journal.sink import JournalSink
from ..journal.store import JournalStore, RunMeta, RunStatus, utc_now
from ..templates.store import TemplateError, TemplateStore


class RunRequestError(ValueError):
    """The request cannot be turned into a valid run."""


@dataclass(slots=True)
class RunRequest:
    model_id: str
    template_name: str | None = None
    goal: str | None = None
    provider: str = "openrouter"
    api_key: str = ""


def _build_provider(request: RunRequest, template_name: str | None) -> Provider:
    if request.provider == "mock":
        from ..demo import build_demo_provider, build_template_demo_provider
        from ..demo_voxel import build_voxel_demo_provider

        if template_name == "minecraft-clone":
            return build_voxel_demo_provider()
        if template_name is not None:
            return build_template_demo_provider()
        return build_demo_provider()

    try:
        return OpenRouterProvider(request.model_id, api_key=request.api_key)
    except ProviderError as exc:
        raise RunRequestError(str(exc)) from exc


class RunService:
    def __init__(
        self,
        *,
        store: JournalStore,
        registry: RunRegistry,
        templates: TemplateStore,
        catalog: CatalogService,
        screenshot_root: Path,
    ) -> None:
        self._store = store
        self._registry = registry
        self._templates = templates
        self._catalog = catalog
        self._screenshot_root = screenshot_root
        self._tasks: dict[str, asyncio.Task[None]] = {}

    # ------------------------------------------------------------------ start

    def start(self, request: RunRequest) -> RunMeta:
        """Validate, record and launch. Returns immediately — the run keeps going."""
        template = None
        if request.template_name:
            try:
                template = self._templates.load(request.template_name)
            except TemplateError as exc:
                raise RunRequestError(str(exc)) from exc

        if template is None and not (request.goal or "").strip():
            raise RunRequestError("Either template or goal is required")

        provider = _build_provider(request, request.template_name)
        model_id = request.model_id or provider.model_id

        config = (
            config_from_template(template, model_id=model_id)
            if template is not None
            else RunConfig(model_id=model_id, goal=request.goal or "")
        )

        run_id = uuid.uuid4().hex[:12]
        meta = RunMeta(
            run_id=run_id,
            model_id=model_id,
            started_at=utc_now(),
            goal=config.goal,
            template_ref=template.ref if template else None,
            template_hash=template.content_hash if template else None,
            provider=request.provider,
        )
        self._store.create(meta)

        live = self._registry.create(run_id)
        sink = JournalSink(self._store, run_id, live)

        # Must be called from the event loop thread. A sync FastAPI endpoint would run this
        # in the threadpool, where create_task fails — hence the explicit check with a
        # message that names the cause instead of a bare RuntimeError.
        try:
            asyncio.get_running_loop()
        except RuntimeError as exc:
            raise RunRequestError(
                "RunService.start must be called from the event loop — "
                "the API endpoint has to be 'async def'"
            ) from exc

        task = asyncio.create_task(self._execute(config, provider, sink, meta))
        self._tasks[run_id] = task
        task.add_done_callback(lambda _: self._tasks.pop(run_id, None))
        return meta

    async def _execute(
        self,
        config: RunConfig,
        provider: Provider,
        sink: JournalSink,
        meta: RunMeta,
    ) -> None:
        try:
            outcome = await execute_run(
                config,
                provider=provider,
                catalog=self._catalog,
                templates=self._templates if config.template else None,
                screenshot_dir=self._screenshot_root / meta.run_id,
                run_id=meta.run_id,
                sink=sink,
            )
            self._finalise(meta, outcome)
        except Exception as exc:
            # A crashed run must still be readable — an entry stuck on "running" forever
            # would be worse than a recorded failure.
            meta.status = RunStatus.FAILED
            meta.stop_reason = "error"
            meta.detail = f"{type(exc).__name__}: {exc}"
            meta.finished_at = utc_now()
            self._store.write_meta(meta)
        finally:
            self._registry.finish(meta.run_id)
            # Teardown must never mask the real outcome of the run.
            with contextlib.suppress(Exception):
                await provider.aclose()

    def _finalise(self, meta: RunMeta, outcome: RunOutcome) -> None:
        result = outcome.result
        budget = result.budget

        meta.status = RunStatus.COMPLETED
        meta.finished_at = utc_now()
        meta.stop_reason = result.stop_reason.value
        meta.detail = result.detail
        meta.workspace = outcome.workspace
        meta.pricing_known = outcome.pricing_known
        if budget is not None:
            meta.iterations = budget.iterations
            meta.prompt_tokens = budget.usage.prompt_tokens
            meta.completion_tokens = budget.usage.completion_tokens
            meta.cost_usd = str(budget.cost_usd)

        if outcome.checks is not None:
            meta.checks_passed = outcome.checks.passed
            meta.check_summary = [
                {
                    "name": o.name,
                    "passed": o.passed,
                    "required": o.required,
                    "duration_seconds": round(o.duration_seconds, 2),
                    "detail": o.detail[:2000],
                }
                for o in outcome.checks.outcomes
            ]
            meta.screenshots = sorted(outcome.checks.screenshots)

        self._store.write_meta(meta)

    # ------------------------------------------------------------------ query

    @property
    def store(self) -> JournalStore:
        """The journal behind this service — used by the CLI and by tests."""
        return self._store

    def list_runs(self, *, limit: int = 50) -> list[RunMeta]:
        return [self._reconcile(meta) for meta in self._store.list_runs(limit=limit)]

    def get(self, run_id: str) -> RunMeta | None:
        meta = self._store.read_meta(run_id)
        return None if meta is None else self._reconcile(meta)

    def _reconcile(self, meta: RunMeta) -> RunMeta:
        """Report a run marked ``running`` without a live task as what it is: abandoned.

        Runs live in this process, so a restart — or a task that never started — leaves
        metadata claiming progress that will never come. An entry stuck on "running" forever
        is worse than a recorded failure, so the state is corrected on read and persisted.
        """
        if meta.status is not RunStatus.RUNNING:
            return meta
        if self._registry.get(meta.run_id) is not None:
            return meta

        meta.status = RunStatus.FAILED
        meta.stop_reason = "abandoned"
        meta.detail = "The run did not survive the process it was started in."
        meta.finished_at = meta.finished_at or utc_now()
        self._store.write_meta(meta)
        return meta

    def events(self, run_id: str, *, after: int = -1) -> list[Event]:
        live = self._registry.get(run_id)
        if live is not None:
            # While a run is in flight the in-memory list is authoritative and cheaper than
            # re-reading the file on every poll.
            return [e for e in live.events if e.sequence > after]
        return self._store.read_events(run_id, after=after)

    def is_live(self, run_id: str) -> bool:
        live = self._registry.get(run_id)
        return live is not None and not live.finished

    async def stream(self, run_id: str, *, after: int = -1) -> AsyncIterator[Event]:
        """Live stream for a running run, or the recorded journal for a finished one."""
        if self._registry.get(run_id) is not None:
            async for event in self._registry.stream(run_id, after=after):
                yield event
            return

        for event in self._store.read_events(run_id, after=after):
            yield event

    def screenshot_path(self, run_id: str, name: str) -> Path | None:
        # Only the file name is accepted, never a path — otherwise a crafted name could read
        # arbitrary files through this endpoint.
        if "/" in name or "\\" in name or name.startswith("."):
            return None
        path = self._screenshot_root / run_id / name
        return path if path.is_file() else None

    async def wait(self, run_id: str) -> None:
        """Await completion — used by tests and the CLI, not by the API."""
        task = self._tasks.get(run_id)
        if task is not None:
            await task


UNKNOWN_COST = Decimal(0)
