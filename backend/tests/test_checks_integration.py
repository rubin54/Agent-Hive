"""The check chain against real containers.

The most important test here is not that a good solution passes — it is that a broken one
fails. A check suite that always confirms is worthless and would devalue any later
leaderboard.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hive.checks.runner import run_checks
from hive.sandbox.docker_sandbox import DockerSandbox, SandboxLimits
from hive.templates.store import TemplateStore

from .test_sandbox import requires_docker

REPO = Path(__file__).resolve().parents[2]

GOOD_INDEX = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Counter</title></head>
<body>
  <h1>Counter</h1>
  <output id="value">0</output>
  <button id="increment">+1</button>
  <button id="reset">Reset</button>
  <script src="counter.js"></script>
</body></html>
"""

GOOD_LOGIC = """let count = 0;
const output = document.getElementById("value");
const render = () => { output.textContent = String(count); };
document.getElementById("increment").addEventListener("click", () => { count += 1; render(); });
document.getElementById("reset").addEventListener("click", () => { count = 0; render(); });
render();
"""

# The reset button is wired up but does nothing. Exactly the kind of defect a pure existence
# check would wave through.
BROKEN_LOGIC = """let count = 0;
const output = document.getElementById("value");
const render = () => { output.textContent = String(count); };
document.getElementById("increment").addEventListener("click", () => { count += 1; render(); });
document.getElementById("reset").addEventListener("click", () => { render(); });
render();
"""


async def _prepare(index: str, logic: str) -> tuple[DockerSandbox, TemplateStore, object]:
    store = TemplateStore(REPO / "templates")
    template = store.load("counter-page")
    sandbox = await DockerSandbox.create(
        SandboxLimits(image=template.workspace.image, network=template.workspace.network)
    )
    for path, content in store.starter_files(template):
        await sandbox.write_file(path, content)
    await sandbox.write_file("index.html", index)
    await sandbox.write_file("counter.js", logic)
    return sandbox, store, template


@requires_docker
async def test_working_solution_passes_every_check(tmp_path: Path) -> None:
    sandbox, store, template = await _prepare(GOOD_INDEX, GOOD_LOGIC)
    try:
        report = await run_checks(template, sandbox, store, screenshot_dir=tmp_path)  # type: ignore[arg-type]
    finally:
        await sandbox.destroy()

    assert report.passed, report.format()
    assert [o.name for o in report.outcomes] == [
        "files-present",
        "syntax",
        "serve",
        "behaviour",
    ]
    # Screenshots are produced regardless of the verdict — they go to the judge panel later.
    assert report.screenshots
    assert list(tmp_path.glob("*.png"))


@requires_docker
async def test_broken_behaviour_fails_the_browser_check() -> None:
    """The file is there, the syntax is valid, the server runs — the behaviour is wrong."""
    sandbox, store, template = await _prepare(GOOD_INDEX, BROKEN_LOGIC)
    try:
        report = await run_checks(template, sandbox, store)  # type: ignore[arg-type]
    finally:
        await sandbox.destroy()

    assert not report.passed
    by_name = {o.name: o for o in report.outcomes}
    assert by_name["files-present"].passed
    assert by_name["syntax"].passed
    assert by_name["serve"].passed
    assert not by_name["behaviour"].passed


@requires_docker
async def test_missing_files_stop_the_chain_early() -> None:
    """Without files there is nothing to operate — further checks would waste time."""
    store = TemplateStore(REPO / "templates")
    template = store.load("counter-page")
    sandbox = await DockerSandbox.create(
        SandboxLimits(image=template.workspace.image, network=template.workspace.network)
    )
    try:
        report = await run_checks(template, sandbox, store)
    finally:
        await sandbox.destroy()

    assert not report.passed
    assert report.outcomes[0].name == "files-present"
    assert not report.outcomes[0].passed
    assert report.skipped == ["syntax", "serve", "behaviour"]


@requires_docker
async def test_syntax_error_is_caught_before_the_browser() -> None:
    sandbox, store, template = await _prepare(GOOD_INDEX, "const x = ;;;")
    try:
        report = await run_checks(template, sandbox, store)  # type: ignore[arg-type]
    finally:
        await sandbox.destroy()

    by_name = {o.name: o for o in report.outcomes}
    assert not by_name["syntax"].passed
    assert "serve" in report.skipped


@requires_docker
async def test_internal_network_blocks_the_internet() -> None:
    """The checker reaches the application, the application does not reach the internet.

    Exactly this combination allows browser checks without granting the subject network
    access.
    """
    async with await DockerSandbox.create(SandboxLimits(network="internal")) as sandbox:
        assert sandbox.network_name is not None
        probe = await sandbox.exec(
            "node -e \"fetch('https://example.com').then(()=>console.log('REACHABLE'))"
            ".catch(()=>console.log('BLOCKED'))\"",
            timeout=20,
        )
        assert "BLOCKED" in probe.stdout


@requires_docker
async def test_network_can_be_granted_and_revoked_at_runtime() -> None:
    """Granting access selectively is the stand-in for the missing egress proxy."""
    async with await DockerSandbox.create(SandboxLimits(network="internal")) as sandbox:
        blocked = await sandbox.exec(
            "node -e \"fetch('https://example.com').then(()=>console.log('REACHABLE'))"
            ".catch(()=>console.log('BLOCKED'))\"",
            timeout=20,
        )
        assert "BLOCKED" in blocked.stdout

        name = await sandbox.attach_network("bridge")
        assert name == "bridge"
        granted = await sandbox.exec(
            "node -e \"fetch('https://example.com').then(()=>console.log('REACHABLE'))"
            ".catch(e=>console.log('BLOCKED '+e.message))\"",
            timeout=30,
        )
        assert "REACHABLE" in granted.stdout

        await sandbox.detach_network("bridge")
        revoked = await sandbox.exec(
            "node -e \"fetch('https://example.com').then(()=>console.log('REACHABLE'))"
            ".catch(()=>console.log('BLOCKED'))\"",
            timeout=20,
        )
        assert "BLOCKED" in revoked.stdout


@requires_docker
async def test_none_mode_container_refuses_later_network_grants() -> None:
    """Docker does not allow it — the sandbox says so instead of letting it blow up.

    This boundary is why templates with network needs must request ``internal``.
    """
    from hive.sandbox.docker_sandbox import SandboxError

    async with await DockerSandbox.create(SandboxLimits(network="none")) as sandbox:
        with pytest.raises(SandboxError, match="network='internal'"):
            await sandbox.attach_network("bridge")


def test_template_with_network_needs_rejects_none_mode() -> None:
    """The contradiction surfaces on load, not after ten minutes of agent work."""
    from hive.templates.models import Template

    with pytest.raises(ValueError, match=r"workspace\.network"):
        Template.model_validate(
            {
                "name": "a",
                "version": 1,
                "prompt": "x",
                "workspace": {"network": "none", "agent_internet": True},
            }
        )


@requires_docker
async def test_background_server_survives_the_exec_call() -> None:
    """Without setsid Docker terminates the process as soon as the exec returns."""
    async with await DockerSandbox.create(SandboxLimits(network="internal")) as sandbox:
        await sandbox.write_file(
            "tiny.js",
            "require('node:http').createServer((q,s)=>s.end('hello')).listen(8080,'0.0.0.0');",
        )
        await sandbox.start_background("node tiny.js")
        ready, detail = await sandbox.wait_for_port(8080, timeout_seconds=20)
        assert ready, detail


@requires_docker
async def test_unreachable_port_reports_the_server_log() -> None:
    """Without the log the report would only say "port does not answer" — useless."""
    async with await DockerSandbox.create(SandboxLimits(network="internal")) as sandbox:
        await sandbox.start_background("node -e \"throw new Error('IMMEDIATE_CRASH')\"")
        ready, _ = await sandbox.wait_for_port(9999, timeout_seconds=5)
        assert not ready
        assert "IMMEDIATE_CRASH" in await sandbox.read_log()


def test_webgl_spec_does_not_read_pixels_inside_the_page() -> None:
    """Regression guard for a real failure encountered while building this check.

    ``drawImage(webglCanvas, …)`` and ``canvas.toDataURL()`` return an empty buffer for WebGL
    once the browser discards the drawing buffer after compositing — the default. A check
    built that way failed a perfectly correct voxel scene. The replacement is Playwright
    screenshots, which go through the compositor.
    """
    store = TemplateStore(REPO / "templates")
    template = store.load("minecraft-clone")
    spec = next(c for c in template.checks if c.name == "playability")
    source = store.spec_source(template, spec)  # type: ignore[arg-type]

    # Strip comments: the spec explains this very pitfall in prose, and a plain text search
    # would trip over it.
    code = "\n".join(line for line in source.splitlines() if not line.strip().startswith("//"))

    assert "drawImage" not in code
    assert "toDataURL" not in code
    assert ".screenshot()" in code


@pytest.mark.parametrize("name", ["counter-page", "minecraft-clone"])
def test_shipped_specs_are_valid_typescript_ish(name: str) -> None:
    """Rough check without Docker: a spec must have Playwright imports and tests."""
    store = TemplateStore(REPO / "templates")
    template = store.load(name)
    for check in template.checks:
        if check.__class__.__name__ != "PlaywrightCheck":
            continue
        source = store.spec_source(template, check)  # type: ignore[arg-type]
        assert "@playwright/test" in source
        assert "test(" in source
