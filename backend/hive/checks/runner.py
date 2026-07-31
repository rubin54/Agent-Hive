"""Execution of the template checks after an agent run.

This is the L1/L2 evaluation from the plan: mechanical, deterministic, free. It provides the
objective foundation that the judge panel (L3) and pairwise comparison (L4) build on later —
and it already decides a lot on its own, because "does not build" makes any rubric discussion
moot.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path

from ..sandbox.docker_sandbox import DockerSandbox, SandboxError
from ..templates.models import (
    CheckKind,
    CommandCheck,
    PlaywrightCheck,
    ServeCheck,
    Template,
)
from ..templates.store import TemplateStore
from .playwright_runner import PlaywrightChecker


@dataclass(slots=True)
class CheckOutcome:
    name: str
    kind: CheckKind
    passed: bool
    required: bool
    detail: str
    duration_seconds: float

    @property
    def blocking_failure(self) -> bool:
        return self.required and not self.passed


@dataclass(slots=True)
class CheckReport:
    outcomes: list[CheckOutcome] = field(default_factory=list)
    screenshots: dict[str, bytes] = field(default_factory=dict)
    skipped: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not any(o.blocking_failure for o in self.outcomes)

    def format(self) -> str:
        lines = []
        for outcome in self.outcomes:
            mark = "OK  " if outcome.passed else ("FAIL" if outcome.required else "warn")
            lines.append(f"  [{mark}] {outcome.name} ({outcome.duration_seconds:.1f}s)")
            if not outcome.passed:
                detail = outcome.detail.strip().splitlines()
                lines.extend(f"         {line}" for line in detail[:6])
        for name in self.skipped:
            lines.append(f"  [--  ] {name} — skipped")
        if self.screenshots:
            lines.append(f"  {len(self.screenshots)} screenshots captured")
        return "\n".join(lines) or "  (no checks defined)"


async def run_checks(
    template: Template,
    sandbox: DockerSandbox,
    store: TemplateStore,
    *,
    screenshot_dir: Path | None = None,
) -> CheckReport:
    """Run all checks of a template against the workspace."""
    report = CheckReport()
    served: dict[int, bool] = {}

    for check in template.checks:
        # Running the remaining checks after a blocking failure would be a waste of time:
        # without a successful build there is nothing to operate.
        if not report.passed:
            report.skipped.append(check.name)
            continue

        started = time.monotonic()
        match check:
            case CommandCheck():
                outcome = await _run_command(check, sandbox, started)
            case ServeCheck():
                outcome = await _run_serve(check, sandbox, started)
                served[check.port] = outcome.passed
            case PlaywrightCheck():
                if not served.get(check.port):
                    report.skipped.append(check.name)
                    continue
                outcome = await _run_playwright(check, template, sandbox, store, report, started)
            case _:  # pragma: no cover - excluded by the schema
                continue
        report.outcomes.append(outcome)

    if screenshot_dir is not None and report.screenshots:
        screenshot_dir.mkdir(parents=True, exist_ok=True)
        for name, payload in report.screenshots.items():
            (screenshot_dir / name).write_bytes(payload)

    return report


async def _run_command(check: CommandCheck, sandbox: DockerSandbox, started: float) -> CheckOutcome:
    network: str | None = None
    if check.needs_network:
        # Network access for this one command only. Leaving it open for the whole run would
        # be more convenient and considerably worse.
        network = await sandbox.attach_network("bridge")
    try:
        result = await sandbox.exec(check.command, timeout=check.timeout_seconds)
    except SandboxError as exc:
        return CheckOutcome(
            check.name, check.kind, False, check.required, str(exc), time.monotonic() - started
        )
    finally:
        if network:
            await sandbox.detach_network(network)

    return CheckOutcome(
        name=check.name,
        kind=check.kind,
        passed=result.ok,
        required=check.required,
        detail=result.combined(),
        duration_seconds=time.monotonic() - started,
    )


async def _run_serve(check: ServeCheck, sandbox: DockerSandbox, started: float) -> CheckOutcome:
    await sandbox.start_background(check.command)
    ready, detail = await sandbox.wait_for_port(
        check.port, path=check.path, timeout_seconds=check.ready_timeout_seconds
    )
    if not ready:
        # The server log is the only usable source of failure information here — without it
        # the report would just say "port does not answer", which helps nobody.
        log = await sandbox.read_log()
        detail = f"{detail}\n[server log]\n{log}" if log else detail

    return CheckOutcome(
        name=check.name,
        kind=check.kind,
        passed=ready,
        required=check.required,
        detail=detail,
        duration_seconds=time.monotonic() - started,
    )


async def _run_playwright(
    check: PlaywrightCheck,
    template: Template,
    sandbox: DockerSandbox,
    store: TemplateStore,
    report: CheckReport,
    started: float,
) -> CheckOutcome:
    network = sandbox.network_name
    if network is None:
        return CheckOutcome(
            name=check.name,
            kind=check.kind,
            passed=False,
            required=check.required,
            detail=(
                "No shared network: the checker container cannot reach the application. "
                "The template needs workspace.network = internal."
            ),
            duration_seconds=time.monotonic() - started,
        )

    spec = store.spec_source(template, check)
    base_url = f"http://{sandbox.hostname}:{check.port}"

    async with await PlaywrightChecker.create(network) as checker:
        outcome = await checker.run_spec(
            spec,
            base_url=base_url,
            timeout_seconds=check.timeout_seconds,
            screenshots=check.screenshots,
        )

    report.screenshots.update(outcome.screenshots)
    return CheckOutcome(
        name=check.name,
        kind=check.kind,
        passed=outcome.passed,
        required=check.required,
        detail=outcome.output,
        duration_seconds=time.monotonic() - started,
    )
