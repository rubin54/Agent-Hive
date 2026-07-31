"""Isolated execution environment based on Docker.

Models write and **execute** code. That is not a theoretical risk, which is why the
protections here are mandatory rather than decorative:

- one container per run, non-root user, all capabilities dropped, ``no-new-privileges``
- no host mounts — the workspace lives inside the container only
- hard limits on memory, CPU, processes and the runtime of individual commands
- capped output volume so a build log cannot blow up the model's context

**Known gap:** the planned egress proxy with an allowlist (package registries only) is still
missing. ``network="none"`` is the default; anything needing package installation switches to
``internal`` deliberately and grants ``bridge`` only for the duration of a single command.
"""

from __future__ import annotations

import asyncio
import contextlib
import io
import shlex
import tarfile
import uuid
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Literal

import docker
from docker.errors import DockerException, ImageNotFound, NotFound

WORKSPACE = "/workspace"
DEFAULT_IMAGE = "hive/node-web:1"
IMAGE_DIR = Path(__file__).resolve().parents[3] / "docker"

# "internal" is the interesting mode: a user-defined Docker network with ``internal=True``.
# Containers inside reach each other but not the internet. That lets the checker container
# talk to the application without giving the application any way out.
NetworkMode = Literal["none", "bridge", "internal"]


class SandboxError(RuntimeError):
    """The sandbox could not be provisioned or operated."""


@dataclass(frozen=True, slots=True)
class SandboxLimits:
    image: str = DEFAULT_IMAGE
    memory_mb: int = 2048
    cpus: float = 2.0
    pids: int = 512
    network: NetworkMode = "none"
    #: Time limit per individual command. Enforced by `timeout` inside the container, so it
    #: actually kills the process.
    command_timeout_seconds: int = 300
    #: Upper bound on tool output. `npm install` otherwise produces tens of thousands of
    #: lines that would land in the context window as a tool result.
    max_output_bytes: int = 20_000


@dataclass(frozen=True, slots=True)
class ExecResult:
    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool = False

    @property
    def ok(self) -> bool:
        return self.exit_code == 0

    def combined(self) -> str:
        parts = []
        if self.stdout.strip():
            parts.append(self.stdout.rstrip())
        if self.stderr.strip():
            parts.append(f"[stderr]\n{self.stderr.rstrip()}")
        if self.timed_out:
            parts.append("[command was aborted after exceeding its time limit]")
        body = "\n".join(parts) if parts else "(no output)"
        return f"exit={self.exit_code}\n{body}"


def _truncate(raw: bytes, limit: int) -> str:
    text = raw.decode("utf-8", errors="replace")
    if len(text) <= limit:
        return text
    half = limit // 2
    dropped = len(text) - 2 * half
    return f"{text[:half]}\n… [{dropped} characters omitted] …\n{text[-half:]}"


class DockerSandbox:
    """One container serving as the workspace of a run."""

    def __init__(
        self,
        client: Any,
        container: Any,
        limits: SandboxLimits,
        network_name: str | None = None,
    ) -> None:
        self._client = client
        self._container = container
        self._limits = limits
        self._network_name = network_name
        #: The mode at creation time decides whether networks may be added later.
        self._created_mode: NetworkMode = limits.network

    @property
    def hostname(self) -> str:
        """Container name — on a user-defined network also its DNS name."""
        return str(self._container.name)

    @property
    def network_name(self) -> str | None:
        return self._network_name

    # ----------------------------------------------------------------- creation

    @classmethod
    async def create(cls, limits: SandboxLimits | None = None) -> DockerSandbox:
        limits = limits or SandboxLimits()
        return await asyncio.to_thread(cls._create_blocking, limits)

    @staticmethod
    def _create_blocking(limits: SandboxLimits) -> DockerSandbox:
        try:
            client = docker.from_env()
            client.ping()
        except DockerException as exc:
            raise SandboxError(
                f"Docker unreachable: {exc}. Is Docker Desktop or the daemon running?"
            ) from exc

        DockerSandbox._ensure_image(client, limits.image)

        name = f"hive-{uuid.uuid4().hex[:12]}"
        network_name: str | None = None
        kwargs: dict[str, Any] = {}

        if limits.network == "internal":
            network_name = f"hive-net-{uuid.uuid4().hex[:8]}"
            try:
                client.networks.create(network_name, driver="bridge", internal=True)
            except DockerException as exc:
                raise SandboxError(f"Network could not be created: {exc}") from exc
            kwargs["network"] = network_name
        else:
            kwargs["network_mode"] = limits.network

        try:
            container = client.containers.run(
                limits.image,
                command=["sleep", "infinity"],
                detach=True,
                name=name,
                working_dir=WORKSPACE,
                mem_limit=f"{limits.memory_mb}m",
                nano_cpus=int(limits.cpus * 1_000_000_000),
                pids_limit=limits.pids,
                cap_drop=["ALL"],
                security_opt=["no-new-privileges"],
                # No host mount: the workspace only leaves the container through explicit
                # file reads.
                volumes={},
                auto_remove=False,
                **kwargs,
            )
        except DockerException as exc:
            raise SandboxError(f"Container could not be started: {exc}") from exc

        return DockerSandbox(client, container, limits, network_name)

    @staticmethod
    def _ensure_image(client: Any, image: str) -> None:
        try:
            client.images.get(image)
            return
        except ImageNotFound:
            pass

        dockerfile = IMAGE_DIR / "node-web.Dockerfile"
        if image == DEFAULT_IMAGE and dockerfile.is_file():
            try:
                client.images.build(
                    path=str(IMAGE_DIR),
                    dockerfile=dockerfile.name,
                    tag=image,
                    rm=True,
                )
                return
            except DockerException as exc:
                raise SandboxError(f"Image '{image}' could not be built: {exc}") from exc

        try:
            client.images.pull(image)
        except DockerException as exc:
            raise SandboxError(f"Image '{image}' is missing and cannot be pulled: {exc}") from exc

    # ---------------------------------------------------------------- operation

    async def exec(self, command: str, *, timeout: int | None = None) -> ExecResult:
        limit = timeout or self._limits.command_timeout_seconds
        return await asyncio.to_thread(self._exec_blocking, command, limit)

    def _exec_blocking(self, command: str, timeout: int) -> ExecResult:
        # `timeout` runs inside the container and really terminates the process. A time limit
        # on the Python side would only abort the wait and leave the process running.
        # Separate streams (demux) are valuable for build failures.
        try:
            exit_code, (stdout, stderr) = self._container.exec_run(
                ["sh", "-lc", f"timeout {timeout}s {command}"],
                workdir=WORKSPACE,
                demux=True,
            )
        except DockerException as exc:
            raise SandboxError(f"Command failed: {exc}") from exc

        return ExecResult(
            exit_code=int(exit_code),
            stdout=_truncate(stdout or b"", self._limits.max_output_bytes),
            stderr=_truncate(stderr or b"", self._limits.max_output_bytes),
            # 124 is the exit code coreutils `timeout` uses to report an abort.
            timed_out=int(exit_code) == 124,
        )

    async def start_background(self, command: str, *, log_file: str = "/tmp/serve.log") -> None:
        """Start a process that outlives the call (a dev server).

        ``setsid`` detaches the process from the exec session; without it Docker terminates it
        as soon as the ``exec`` returns, and the readiness probe that follows would always
        fail.
        """
        await asyncio.to_thread(
            self._container.exec_run,
            ["sh", "-lc", f"setsid sh -c {shlex.quote(command)} > {log_file} 2>&1 < /dev/null &"],
            workdir=WORKSPACE,
            detach=True,
        )

    async def wait_for_port(
        self, port: int, *, path: str = "/", timeout_seconds: int = 60
    ) -> tuple[bool, str]:
        """Wait until the port answers HTTP inside the container.

        The probe runs **inside** the container: with ``network="none"`` there is no way in
        from the host, and with ``internal`` there is none either. Node is in the image
        anyway, so no extra tooling is needed.
        """
        probe = (
            "const t=Date.now();"
            f"const deadline=t+{timeout_seconds * 1000};"
            "(async()=>{while(Date.now()<deadline){"
            f"try{{const r=await fetch('http://127.0.0.1:{port}{path}');"
            "console.log('READY '+r.status);process.exit(0);}"
            "catch(e){await new Promise(r=>setTimeout(r,500));}}"
            "console.log('TIMEOUT');process.exit(1);})()"
        )
        result = await self.exec(f"node -e {shlex.quote(probe)}", timeout=timeout_seconds + 10)
        return result.ok, result.stdout.strip() or result.stderr.strip()

    async def read_log(self, log_file: str = "/tmp/serve.log") -> str:
        result = await self.exec(f"tail -c 4000 {log_file} 2>/dev/null || true")
        return result.stdout.strip()

    # ------------------------------------------------------------------ network

    async def attach_network(self, mode: NetworkMode) -> str | None:
        """Attach the container to a network at runtime and return its name.

        This grants network access selectively — for a single ``npm install``, say — and
        revokes it right after, instead of leaving it open for the whole run.

        **Docker limitation:** a container started with ``network_mode=none`` cannot be
        attached to any network afterwards. Anything needing selective access must create the
        sandbox with ``network="internal"``, which shields from the internet just as well but
        allows adding networks later.
        """
        if mode == "none":
            return None
        if self._created_mode == "none":
            raise SandboxError(
                "Container was started with network='none' and cannot be attached to any "
                "network afterwards (Docker limitation). For selective network access, "
                "create the sandbox with network='internal'."
            )
        name = "bridge" if mode == "bridge" else f"hive-net-{uuid.uuid4().hex[:8]}"
        return await asyncio.to_thread(self._attach_blocking, name, mode)

    def _attach_blocking(self, name: str, mode: NetworkMode) -> str:
        try:
            if mode == "internal":
                network = self._client.networks.create(name, driver="bridge", internal=True)
            else:
                network = self._client.networks.get(name)
            network.connect(self._container)
        except DockerException as exc:
            raise SandboxError(f"Network '{name}' could not be connected: {exc}") from exc
        if mode == "internal":
            self._network_name = name
        return name

    async def detach_network(self, name: str, *, remove: bool = False) -> None:
        await asyncio.to_thread(self._detach_blocking, name, remove)

    def _detach_blocking(self, name: str, remove: bool) -> None:
        with contextlib.suppress(DockerException):
            network = self._client.networks.get(name)
            network.disconnect(self._container, force=True)
            if remove:
                network.remove()
        if self._network_name == name:
            self._network_name = None

    # -------------------------------------------------------------------- files

    async def write_file(self, path: str, content: str) -> None:
        await asyncio.to_thread(self._write_blocking, path, content)

    def _write_blocking(self, path: str, content: str) -> None:
        target = self._absolute(path)
        payload = content.encode("utf-8")

        stream = io.BytesIO()
        with tarfile.open(fileobj=stream, mode="w") as archive:
            info = tarfile.TarInfo(name=PurePosixPath(target).name)
            info.size = len(payload)
            info.mode = 0o644
            archive.addfile(info, io.BytesIO(payload))
        stream.seek(0)

        parent = PurePosixPath(target).parent.as_posix()
        # Create the directory before extracting — put_archive does not create missing
        # intermediate directories.
        self._container.exec_run(["mkdir", "-p", parent])
        if not self._container.put_archive(parent, stream.read()):
            raise SandboxError(f"File could not be written: {path}")

    async def read_file(self, path: str) -> str:
        return await asyncio.to_thread(self._read_blocking, path)

    def _read_blocking(self, path: str) -> str:
        target = self._absolute(path)
        try:
            stream, _ = self._container.get_archive(target)
        except NotFound as exc:
            raise SandboxError(f"File not found: {path}") from exc
        except DockerException as exc:
            raise SandboxError(f"File not readable: {path} ({exc})") from exc

        buffer = io.BytesIO(b"".join(stream))
        buffer.seek(0)
        with tarfile.open(fileobj=buffer, mode="r") as archive:
            member = next((m for m in archive.getmembers() if m.isfile()), None)
            if member is None:
                raise SandboxError(f"No file content in {path}")
            extracted = archive.extractfile(member)
            if extracted is None:
                raise SandboxError(f"No file content in {path}")
            return _truncate(extracted.read(), self._limits.max_output_bytes)

    @staticmethod
    def _absolute(path: str) -> str:
        """Map a model-supplied path onto a path inside the workspace.

        Deliberately using ``PurePosixPath`` with hand-rolled normalisation: ``Path.resolve()``
        on a Windows host would resolve against the *host* filesystem and turn ``/workspace/x``
        into ``C:\\workspace\\x`` — the escape guard would then be worthless.
        """
        clean = path.replace("\\", "/").strip()
        if clean.startswith(f"{WORKSPACE}/") or clean == WORKSPACE:
            clean = clean[len(WORKSPACE) :]
        clean = clean.lstrip("/")

        parts: list[str] = []
        for segment in PurePosixPath(clean).parts:
            if segment in (".", ""):
                continue
            if segment == "..":
                if not parts:
                    raise SandboxError(f"Path lies outside the workspace: {path}")
                parts.pop()
                continue
            parts.append(segment)

        return PurePosixPath(WORKSPACE, *parts).as_posix()

    # ----------------------------------------------------------------- teardown

    async def destroy(self) -> None:
        await asyncio.to_thread(self._destroy_blocking)

    def _destroy_blocking(self) -> None:
        # An already-vanished container is not an error anyone needs to see.
        with contextlib.suppress(DockerException):
            self._container.remove(force=True)
        # Networks we created must go too, otherwise hundreds of unused bridges pile up
        # across runs and the address space for new networks runs out.
        if self._network_name:
            with contextlib.suppress(DockerException):
                self._client.networks.get(self._network_name).remove()
            self._network_name = None

    async def __aenter__(self) -> DockerSandbox:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.destroy()
