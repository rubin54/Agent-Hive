"""Functional browser checks — in a container of their own next to the sandbox.

The separation is the point: the checker container joins the same ``internal`` network as the
sandbox and reaches it by container name. It is therefore unreachable from the subject under
test, let alone modifiable — unlike a check running inside the very container the model is
free to write to.
"""

from __future__ import annotations

import asyncio
import contextlib
import io
import tarfile
import uuid
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

import docker
from docker.errors import DockerException, ImageNotFound

from ..sandbox.docker_sandbox import IMAGE_DIR, SandboxError

CHECKER_IMAGE = "hive/playwright-checker:1"
CHECKER_DIR = "/checker"

# Minimal configuration. `baseURL` points at the sandbox container, so a template's spec
# works with relative paths and never needs to know the hostname.
PLAYWRIGHT_CONFIG = """import {{ defineConfig }} from "@playwright/test";

export default defineConfig({{
  testDir: "./tests",
  timeout: {timeout_ms},
  retries: 0,
  reporter: [["json", {{ outputFile: "results.json" }}], ["list"]],
  outputDir: "./artifacts",
  use: {{
    baseURL: "{base_url}",
    screenshot: "only-on-failure",
    trace: "off",
  }},
}});
"""


@dataclass(slots=True)
class PlaywrightOutcome:
    passed: bool
    exit_code: int
    output: str
    screenshots: dict[str, bytes]
    results_json: str | None = None


class PlaywrightChecker:
    """A checker container for the duration of one run."""

    def __init__(self, client: Any, container: Any) -> None:
        self._client = client
        self._container = container

    @classmethod
    async def create(cls, network_name: str) -> PlaywrightChecker:
        return await asyncio.to_thread(cls._create_blocking, network_name)

    @staticmethod
    def _create_blocking(network_name: str) -> PlaywrightChecker:
        try:
            client = docker.from_env()
        except DockerException as exc:
            raise SandboxError(f"Docker unreachable: {exc}") from exc

        PlaywrightChecker._ensure_image(client)

        try:
            container = client.containers.run(
                CHECKER_IMAGE,
                command=["sleep", "infinity"],
                detach=True,
                name=f"hive-check-{uuid.uuid4().hex[:10]}",
                working_dir=CHECKER_DIR,
                network=network_name,
                mem_limit="2048m",
                auto_remove=False,
            )
        except DockerException as exc:
            raise SandboxError(f"Checker container could not be started: {exc}") from exc

        return PlaywrightChecker(client, container)

    @staticmethod
    def _ensure_image(client: Any) -> None:
        try:
            client.images.get(CHECKER_IMAGE)
            return
        except ImageNotFound:
            pass

        dockerfile = IMAGE_DIR / "playwright-checker.Dockerfile"
        if not dockerfile.is_file():
            raise SandboxError(f"{dockerfile} is missing — checker image cannot be built")
        try:
            client.images.build(
                path=str(IMAGE_DIR), dockerfile=dockerfile.name, tag=CHECKER_IMAGE, rm=True
            )
        except DockerException as exc:
            raise SandboxError(f"Checker image cannot be built: {exc}") from exc

    async def run_spec(
        self,
        spec_source: str,
        *,
        base_url: str,
        timeout_seconds: int,
        screenshots: int,
    ) -> PlaywrightOutcome:
        await asyncio.to_thread(
            self._write_files, spec_source, base_url, timeout_seconds, screenshots
        )
        return await asyncio.to_thread(self._run_blocking, timeout_seconds)

    def _write_files(
        self, spec_source: str, base_url: str, timeout_seconds: int, screenshots: int
    ) -> None:
        config = PLAYWRIGHT_CONFIG.format(
            base_url=base_url, timeout_ms=max(timeout_seconds, 30) * 1000
        )
        files = {
            "playwright.config.ts": config,
            "tests/app.spec.ts": spec_source,
            # The screenshot run is independent of the template: it captures the state
            # regardless of whether the functional checks pass — the images go to the judge
            # panel later and are informative even when checks fail.
            "tests/zz-screenshots.spec.ts": _screenshot_spec(screenshots),
        }
        for path, content in files.items():
            self._put(path, content)

    def _put(self, relative: str, content: str) -> None:
        payload = content.encode("utf-8")
        target = PurePosixPath(CHECKER_DIR) / relative
        stream = io.BytesIO()
        with tarfile.open(fileobj=stream, mode="w") as archive:
            info = tarfile.TarInfo(name=target.name)
            info.size = len(payload)
            info.mode = 0o644
            archive.addfile(info, io.BytesIO(payload))
        stream.seek(0)
        self._container.exec_run(["mkdir", "-p", target.parent.as_posix()])
        if not self._container.put_archive(target.parent.as_posix(), stream.read()):
            raise SandboxError(f"Check file not writable: {relative}")

    def _run_blocking(self, timeout_seconds: int) -> PlaywrightOutcome:
        exit_code, output = self._container.exec_run(
            ["sh", "-lc", f"timeout {timeout_seconds + 30}s npx playwright test 2>&1"],
            workdir=CHECKER_DIR,
        )
        text = (output or b"").decode("utf-8", errors="replace")
        if len(text) > 20_000:
            text = text[:10_000] + "\n… [truncated] …\n" + text[-10_000:]

        return PlaywrightOutcome(
            passed=int(exit_code) == 0,
            exit_code=int(exit_code),
            output=text,
            screenshots=self._collect("screenshots"),
            results_json=self._read_text("results.json"),
        )

    def _collect(self, directory: str) -> dict[str, bytes]:
        """Fetch generated PNG files out of the checker container."""
        try:
            stream, _ = self._container.get_archive(f"{CHECKER_DIR}/{directory}")
        except DockerException:
            return {}

        buffer = io.BytesIO(b"".join(stream))
        buffer.seek(0)
        images: dict[str, bytes] = {}
        with tarfile.open(fileobj=buffer, mode="r") as archive:
            for member in archive.getmembers():
                if not member.isfile() or not member.name.endswith(".png"):
                    continue
                extracted = archive.extractfile(member)
                if extracted is not None:
                    images[Path(member.name).name] = extracted.read()
        return images

    def _read_text(self, relative: str) -> str | None:
        try:
            stream, _ = self._container.get_archive(f"{CHECKER_DIR}/{relative}")
        except DockerException:
            return None
        buffer = io.BytesIO(b"".join(stream))
        buffer.seek(0)
        with tarfile.open(fileobj=buffer, mode="r") as archive:
            member = next((m for m in archive.getmembers() if m.isfile()), None)
            if member is None:
                return None
            extracted = archive.extractfile(member)
            return extracted.read().decode("utf-8", errors="replace") if extracted else None

    async def destroy(self) -> None:
        await asyncio.to_thread(self._destroy_blocking)

    def _destroy_blocking(self) -> None:
        with contextlib.suppress(DockerException):
            self._container.remove(force=True)

    async def __aenter__(self) -> PlaywrightChecker:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.destroy()


def _screenshot_spec(count: int) -> str:
    """Build a spec that captures the state over time.

    Several shots rather than one: a 3D scene or an animation needs a moment before it shows
    anything — a single snapshot straight after load would be black for most tasks.
    """
    return f"""import {{ test }} from "@playwright/test";

const COUNT = {count};

test("screenshots", async ({{ page }}) => {{
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(String(e)));

  await page.goto("/", {{ waitUntil: "load" }});
  await page.setViewportSize({{ width: 1280, height: 800 }});

  for (let i = 0; i < COUNT; i++) {{
    await page.waitForTimeout(1500);
    await page.screenshot({{ path: `screenshots/shot-${{i}}.png` }});
  }}

  // Console errors are reported but not scored: they are a signal for the judge panel, yet
  // plenty of working pages produce harmless warnings.
  if (errors.length) console.log("PAGE_ERRORS " + errors.length + ": " + errors.join(" | "));
}});
"""
