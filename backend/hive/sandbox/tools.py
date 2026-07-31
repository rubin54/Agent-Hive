"""Tools operating on the sandbox.

The docstrings are part of the interface to the model — they end up verbatim in the prompt.
That is why they are terse and action-oriented rather than explanatory.

Splitting read-only from writing tools is not cosmetic: scouts will later receive only
``READ_ONLY_TOOLS`` because they are meant to plan, not execute.
"""

from __future__ import annotations

from ..harness.tools import ToolError, ToolRegistry, tool_from_function
from .docker_sandbox import DockerSandbox, SandboxError

READ_ONLY_TOOLS = ("read_file", "list_files")
WRITE_TOOLS = ("write_file", "run_command")


def build_tools(sandbox: DockerSandbox, *, read_only: bool = False) -> ToolRegistry:
    """Build the tool set for an agent, bound to one concrete sandbox."""

    async def read_file(path: str) -> str:
        """Read a file from the workspace. Path is relative to /workspace."""
        try:
            return await sandbox.read_file(path)
        except SandboxError as exc:
            raise ToolError(str(exc)) from exc

    async def list_files(path: str = ".") -> str:
        """List files and folders. Path is relative to /workspace, default is the root."""
        # Hide node_modules and .git: without this a listing consists almost entirely of
        # dependencies and eats the context window.
        result = await sandbox.exec(
            f"find {path!r} -maxdepth 3 "
            "-not -path '*/node_modules/*' -not -path '*/.git/*' "
            "-not -name node_modules -not -name .git | sort | head -200"
        )
        if not result.ok:
            raise ToolError(f"Directory not readable: {result.stderr.strip() or path}")
        return result.stdout.strip() or "(empty)"

    async def write_file(path: str, content: str) -> str:
        """Write a file, creating missing folders. Overwrites existing content."""
        try:
            await sandbox.write_file(path, content)
        except SandboxError as exc:
            raise ToolError(str(exc)) from exc
        return f"wrote {path} ({len(content)} characters)"

    async def run_command(command: str) -> str:
        """Run a shell command in the workspace and return exit code and output."""
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
