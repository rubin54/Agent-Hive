"""Provider abstraction.

Kept narrow: a provider receives messages plus tool schemas and returns a ``Completion``.
Everything else — the loop, the budget, tool execution — belongs to the harness. That split is
the precondition for the harness staying the control variable while only the model changes.
"""

from __future__ import annotations

from typing import Any, Protocol

from ..messages import Completion, Message


class ProviderError(RuntimeError):
    """The model call failed for good."""


class Provider(Protocol):
    model_id: str

    async def complete(
        self,
        messages: list[Message],
        *,
        tools: list[dict[str, Any]] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> Completion: ...

    async def aclose(self) -> None: ...
