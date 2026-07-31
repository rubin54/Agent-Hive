"""Task templates: the object under measurement.

A template is **immutable and versioned**. A change produces a new version; older runs keep
their reference version. Without that you end up comparing apples to oranges three weeks
later without noticing — the prompt drifted, the checks got stricter, and the leaderboard
still claims comparability.

As a safeguard every loaded template carries a content hash. Anyone editing the file without
bumping the version shows up when comparing against an older result.
"""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..sandbox.docker_sandbox import NetworkMode


class CheckKind(StrEnum):
    COMMAND = "command"
    SERVE = "serve"
    PLAYWRIGHT = "playwright"


class CommandCheck(BaseModel):
    """A command that must succeed (build, tests, linter)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal[CheckKind.COMMAND] = CheckKind.COMMAND
    name: str
    command: str
    timeout_seconds: int = 300
    #: Requires network access (e.g. `npm install`). Granted for this command only and
    #: revoked immediately afterwards.
    needs_network: bool = False
    #: A failing optional check counts as a finding but does not abort the chain.
    required: bool = True


class ServeCheck(BaseModel):
    """Starts a dev server and waits until it responds."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal[CheckKind.SERVE] = CheckKind.SERVE
    name: str = "serve"
    command: str
    port: int
    path: str = "/"
    ready_timeout_seconds: int = 60
    required: bool = True


class PlaywrightCheck(BaseModel):
    """Functional check in a real browser, including screenshots.

    Runs in its own container next to the sandbox — not *inside* it. Otherwise the checking
    environment would live in the same image the model describes and can modify; a subject
    must not be able to touch its own measuring instrument.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal[CheckKind.PLAYWRIGHT] = CheckKind.PLAYWRIGHT
    name: str = "playwright"
    #: Path to the spec file, relative to the template directory.
    spec: str
    #: Must match a ServeCheck that ran earlier.
    port: int
    timeout_seconds: int = 180
    screenshots: int = 3
    required: bool = True


Check = Annotated[
    CommandCheck | ServeCheck | PlaywrightCheck,
    Field(discriminator="kind"),
]


class Workspace(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    image: str = "hive/node-web:1"
    #: Files present in the workspace before the run. Tasks with starter code are more
    #: objectively assessable than greenfield ones because the goal is defined more tightly.
    starter_dir: str | None = None
    #: Network the container lives in. ``internal`` is a precondition for Playwright checks:
    #: the checker container must reach the application without the application reaching out.
    network: NetworkMode = "none"
    #: Additional internet access **during the agent phase** — needed when the model is
    #: supposed to install packages itself. Revoked afterwards so the check phase sees no
    #: open network.
    agent_internet: bool = False


class Budget(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    max_iterations: int = 30
    max_tokens: int | None = 400_000
    max_wall_clock_seconds: float | None = 1200.0
    max_cost_usd: Decimal | None = Decimal("5.00")


class RubricItem(BaseModel):
    """Scoring criterion for the judge panel (used from M5)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    question: str
    weight: int = 1


class Template(BaseModel):
    """A versioned task definition."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    version: int
    prompt: str
    success_criteria: list[str] = Field(default_factory=list)
    workspace: Workspace = Workspace()
    budget: Budget = Budget()
    checks: list[Check] = Field(default_factory=list)
    rubric: list[RubricItem] = Field(default_factory=list)

    #: Set on load, not maintained in the YAML.
    content_hash: str = ""

    @property
    def ref(self) -> str:
        """Unique identifier of a run, e.g. ``minecraft-clone@3``."""
        return f"{self.name}@{self.version}"

    @model_validator(mode="after")
    def _validate_consistency(self) -> Template:
        names = [check.name for check in self.checks]
        duplicates = {n for n in names if names.count(n) > 1}
        if duplicates:
            raise ValueError(f"Duplicate check names: {', '.join(sorted(duplicates))}")

        # A Playwright check without a server started on the same port would only fail inside
        # the container — here it surfaces immediately.
        served_ports = {c.port for c in self.checks if isinstance(c, ServeCheck)}
        for check in self.checks:
            if isinstance(check, PlaywrightCheck) and check.port not in served_ports:
                raise ValueError(
                    f"Check '{check.name}' targets port {check.port}, "
                    "but no serve check starts anything there"
                )

        # Docker refuses to attach a container started with network_mode=none to any network
        # later. Selective network access therefore requires "internal". Without this check
        # the contradiction would only surface after the expensive agent phase.
        needs_runtime_network = self.workspace.agent_internet or any(
            c.needs_network for c in self.checks if isinstance(c, CommandCheck)
        )
        if needs_runtime_network and self.workspace.network == "none":
            raise ValueError(
                "Runtime network access (agent_internet or needs_network) requires "
                "workspace.network = 'internal' or 'bridge' — a container started with "
                "'none' cannot be attached to a network afterwards"
            )
        return self

    def compute_hash(self) -> str:
        payload = self.model_dump(mode="json", exclude={"content_hash"})
        encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()[:16]

    def with_hash(self) -> Template:
        return self.model_copy(update={"content_hash": self.compute_hash()})

    def summary(self) -> dict[str, Any]:
        return {
            "ref": self.ref,
            "hash": self.content_hash,
            "checks": [c.name for c in self.checks],
            "network": self.workspace.network,
            "max_iterations": self.budget.max_iterations,
        }
