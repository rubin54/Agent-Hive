"""Werkzeuge, die auf der Sandbox arbeiten.

Die Docstrings sind Teil der Schnittstelle zum Modell — sie landen wörtlich im Prompt.
Deshalb sind sie knapp und handlungsorientiert formuliert statt erklärend.

Die Aufteilung in lesende und schreibende Werkzeuge ist keine Kosmetik: Scouts erhalten
später nur ``READ_ONLY_TOOLS``, weil sie planen und nicht ausführen sollen.
"""

from __future__ import annotations

from ..harness.tools import ToolError, ToolRegistry, tool_from_function
from .docker_sandbox import DockerSandbox, SandboxError

READ_ONLY_TOOLS = ("read_file", "list_files")
WRITE_TOOLS = ("write_file", "run_command")


def build_tools(sandbox: DockerSandbox, *, read_only: bool = False) -> ToolRegistry:
    """Baut die Werkzeugsammlung für einen Agenten, gebunden an eine konkrete Sandbox."""

    async def read_file(path: str) -> str:
        """Liest eine Datei aus dem Arbeitsbereich. Pfad relativ zu /workspace."""
        try:
            return await sandbox.read_file(path)
        except SandboxError as exc:
            raise ToolError(str(exc)) from exc

    async def list_files(path: str = ".") -> str:
        """Listet Dateien und Ordner. Pfad relativ zu /workspace, Standard ist die Wurzel."""
        # node_modules und .git ausblenden: Ohne das besteht eine Auflistung fast
        # ausschließlich aus Abhängigkeiten und frisst das Kontextfenster.
        result = await sandbox.exec(
            f"find {path!r} -maxdepth 3 "
            "-not -path '*/node_modules/*' -not -path '*/.git/*' "
            "-not -name node_modules -not -name .git | sort | head -200"
        )
        if not result.ok:
            raise ToolError(f"Verzeichnis nicht lesbar: {result.stderr.strip() or path}")
        return result.stdout.strip() or "(leer)"

    async def write_file(path: str, content: str) -> str:
        """Schreibt eine Datei und legt fehlende Ordner an. Überschreibt vorhandene Inhalte."""
        try:
            await sandbox.write_file(path, content)
        except SandboxError as exc:
            raise ToolError(str(exc)) from exc
        return f"{path} geschrieben ({len(content)} Zeichen)"

    async def run_command(command: str) -> str:
        """Führt einen Shell-Befehl im Arbeitsbereich aus und liefert Exit-Code und Ausgabe."""
        try:
            result = await sandbox.exec(command)
        except SandboxError as exc:
            raise ToolError(str(exc)) from exc
        return result.combined()

    registry = ToolRegistry()
    registry.register(tool_from_function(read_file))
    registry.register(tool_from_function(list_files))
    if not read_only:
        registry.register(tool_from_function(write_file))
        registry.register(tool_from_function(run_command))
    return registry
