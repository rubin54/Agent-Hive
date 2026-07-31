"""Isolierte Ausführungsumgebung auf Docker-Basis.

Modelle schreiben und **führen** Code aus. Das ist kein theoretisches Risiko, deshalb sind
die Schutzmaßnahmen hier Pflicht und nicht Kür:

- ein Container pro Lauf, Nutzer ohne Root, alle Capabilities entzogen, ``no-new-privileges``
- keine Host-Mounts — der Arbeitsbereich lebt ausschließlich im Container
- harte Limits für Speicher, CPU, Prozesse und Laufzeit einzelner Befehle
- gekappte Ausgabemengen, damit ein Build-Log nicht den Kontext des Modells sprengt

**Bekannte Lücke:** Das Netzwerk ist derzeit nur ganz an oder ganz aus. Der im Plan
vorgesehene Egress-Proxy mit Allowlist (nur Paketregistries) fehlt noch. Bis dahin gilt
``network="none"`` als Voreinstellung; wer Pakete installieren lassen will, schaltet bewusst
auf ``bridge`` und weiß, dass der Container dann ins offene Netz darf.
"""

from __future__ import annotations

import asyncio
import contextlib
import io
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

NetworkMode = Literal["none", "bridge"]


class SandboxError(RuntimeError):
    """Die Sandbox konnte nicht bereitgestellt oder bedient werden."""


@dataclass(frozen=True, slots=True)
class SandboxLimits:
    image: str = DEFAULT_IMAGE
    memory_mb: int = 2048
    cpus: float = 2.0
    pids: int = 512
    network: NetworkMode = "none"
    #: Zeitlimit je Einzelbefehl. Greift im Container über `timeout`, tötet also wirklich.
    command_timeout_seconds: int = 300
    #: Obergrenze für Werkzeugausgaben. `npm install` erzeugt sonst zehntausende Zeilen,
    #: die als Tool-Ergebnis direkt ins Kontextfenster wandern würden.
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
            parts.append("[Befehl wurde wegen Zeitüberschreitung abgebrochen]")
        body = "\n".join(parts) if parts else "(keine Ausgabe)"
        return f"exit={self.exit_code}\n{body}"


def _truncate(raw: bytes, limit: int) -> str:
    text = raw.decode("utf-8", errors="replace")
    if len(text) <= limit:
        return text
    half = limit // 2
    dropped = len(text) - 2 * half
    return f"{text[:half]}\n… [{dropped} Zeichen ausgelassen] …\n{text[-half:]}"


class DockerSandbox:
    """Ein Container als Arbeitsbereich eines Laufs."""

    def __init__(self, client: Any, container: Any, limits: SandboxLimits) -> None:
        self._client = client
        self._container = container
        self._limits = limits

    # ------------------------------------------------------------------ Aufbau

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
                f"Docker nicht erreichbar: {exc}. Läuft Docker Desktop bzw. der Daemon?"
            ) from exc

        DockerSandbox._ensure_image(client, limits.image)

        try:
            container = client.containers.run(
                limits.image,
                command=["sleep", "infinity"],
                detach=True,
                name=f"hive-{uuid.uuid4().hex[:12]}",
                working_dir=WORKSPACE,
                network_mode=limits.network,
                mem_limit=f"{limits.memory_mb}m",
                nano_cpus=int(limits.cpus * 1_000_000_000),
                pids_limit=limits.pids,
                cap_drop=["ALL"],
                security_opt=["no-new-privileges"],
                # Kein Host-Mount: Der Arbeitsbereich verlässt den Container nur über
                # ausdrückliches Auslesen von Dateien.
                volumes={},
                auto_remove=False,
            )
        except DockerException as exc:
            raise SandboxError(f"Container konnte nicht gestartet werden: {exc}") from exc

        return DockerSandbox(client, container, limits)

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
                raise SandboxError(f"Image '{image}' konnte nicht gebaut werden: {exc}") from exc

        try:
            client.images.pull(image)
        except DockerException as exc:
            raise SandboxError(f"Image '{image}' fehlt und ist nicht ladbar: {exc}") from exc

    # ------------------------------------------------------------------ Betrieb

    async def exec(self, command: str, *, timeout: int | None = None) -> ExecResult:
        limit = timeout or self._limits.command_timeout_seconds
        return await asyncio.to_thread(self._exec_blocking, command, limit)

    def _exec_blocking(self, command: str, timeout: int) -> ExecResult:
        # `timeout` läuft im Container und beendet den Prozess wirklich. Ein Zeitlimit auf
        # der Python-Seite würde nur das Warten abbrechen und den Prozess weiterlaufen lassen.
        # Getrennte Ströme (demux) sind für Build-Fehler wertvoll.
        try:
            exit_code, (stdout, stderr) = self._container.exec_run(
                ["sh", "-lc", f"timeout {timeout}s {command}"],
                workdir=WORKSPACE,
                demux=True,
            )
        except DockerException as exc:
            raise SandboxError(f"Befehl fehlgeschlagen: {exc}") from exc

        return ExecResult(
            exit_code=int(exit_code),
            stdout=_truncate(stdout or b"", self._limits.max_output_bytes),
            stderr=_truncate(stderr or b"", self._limits.max_output_bytes),
            # 124 ist der Exit-Code, mit dem coreutils `timeout` einen Abbruch meldet.
            timed_out=int(exit_code) == 124,
        )

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
        # Verzeichnis anlegen, bevor das Archiv entpackt wird — put_archive legt keine
        # fehlenden Zwischenverzeichnisse an.
        self._container.exec_run(["mkdir", "-p", parent])
        if not self._container.put_archive(parent, stream.read()):
            raise SandboxError(f"Datei konnte nicht geschrieben werden: {path}")

    async def read_file(self, path: str) -> str:
        return await asyncio.to_thread(self._read_blocking, path)

    def _read_blocking(self, path: str) -> str:
        target = self._absolute(path)
        try:
            stream, _ = self._container.get_archive(target)
        except NotFound as exc:
            raise SandboxError(f"Datei nicht gefunden: {path}") from exc
        except DockerException as exc:
            raise SandboxError(f"Datei nicht lesbar: {path} ({exc})") from exc

        buffer = io.BytesIO(b"".join(stream))
        buffer.seek(0)
        with tarfile.open(fileobj=buffer, mode="r") as archive:
            member = next((m for m in archive.getmembers() if m.isfile()), None)
            if member is None:
                raise SandboxError(f"Kein Dateiinhalt in {path}")
            extracted = archive.extractfile(member)
            if extracted is None:
                raise SandboxError(f"Kein Dateiinhalt in {path}")
            return _truncate(extracted.read(), self._limits.max_output_bytes)

    @staticmethod
    def _absolute(path: str) -> str:
        """Rechnet einen Modellpfad auf einen Pfad im Arbeitsbereich um.

        Bewusst mit ``PurePosixPath`` und eigener Normalisierung: ``Path.resolve()`` würde
        auf einem Windows-Host gegen das *Host*-Dateisystem auflösen und aus ``/workspace/x``
        ein ``C:\\workspace\\x`` machen — der Ausbruchsschutz liefe dann ins Leere.
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
                    raise SandboxError(f"Pfad liegt außerhalb des Arbeitsbereichs: {path}")
                parts.pop()
                continue
            parts.append(segment)

        return PurePosixPath(WORKSPACE, *parts).as_posix()

    # ------------------------------------------------------------------- Abbau

    async def destroy(self) -> None:
        await asyncio.to_thread(self._destroy_blocking)

    def _destroy_blocking(self) -> None:
        # Ein bereits verschwundener Container ist kein Fehler, den jemand sehen muss.
        with contextlib.suppress(DockerException):
            self._container.remove(force=True)

    async def __aenter__(self) -> DockerSandbox:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.destroy()
