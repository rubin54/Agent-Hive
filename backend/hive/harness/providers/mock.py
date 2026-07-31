"""Deterministic mock provider.

The foundation for tests, CI and a turnkey demo: the harness can be exercised completely —
real sandbox, real tools, real files — without a single API call. Without this piece there
would be no regression check and no ``make demo`` without a key.

From M9 a replay provider joins it, playing back recorded real runs.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from ..messages import Completion, FinishReason, Message, ToolCall, Usage
from .base import ProviderError

# Instead of fixed answers a script step can be a function reacting to the conversation so
# far — that makes correction loops expressible.
ScriptStep = Completion | Callable[[list[Message]], Completion]


def say(content: str, *, prompt_tokens: int = 100, completion_tokens: int = 20) -> Completion:
    """A final text answer."""
    return Completion(
        message=Message.assistant(content),
        usage=Usage(prompt_tokens=prompt_tokens, completion_tokens=completion_tokens),
        finish_reason=FinishReason.STOP,
    )


def call(
    name: str,
    arguments: dict[str, Any],
    *,
    call_id: str | None = None,
    prompt_tokens: int = 100,
    completion_tokens: int = 30,
) -> Completion:
    """A single tool call."""
    return Completion(
        message=Message.assistant(
            None,
            tool_calls=[ToolCall(id=call_id or f"call_{name}", name=name, arguments=arguments)],
        ),
        usage=Usage(prompt_tokens=prompt_tokens, completion_tokens=completion_tokens),
        finish_reason=FinishReason.TOOL_CALLS,
    )


def calls(
    requested: Sequence[tuple[str, dict[str, Any]]],
    *,
    prompt_tokens: int = 100,
    completion_tokens: int = 40,
) -> Completion:
    """Several tools in one response — models parallel tool calls."""
    tool_calls = [
        ToolCall(id=f"call_{index}_{name}", name=name, arguments=arguments)
        for index, (name, arguments) in enumerate(requested)
    ]
    return Completion(
        message=Message.assistant(None, tool_calls=tool_calls),
        usage=Usage(prompt_tokens=prompt_tokens, completion_tokens=completion_tokens),
        finish_reason=FinishReason.TOOL_CALLS,
    )


class MockProvider:
    """Plays back a fixed script. Every call consumes one step."""

    def __init__(self, script: Sequence[ScriptStep], *, model_id: str = "mock/scripted") -> None:
        self.model_id = model_id
        self._script = list(script)
        self._index = 0
        self.received: list[list[Message]] = []

    @property
    def calls_made(self) -> int:
        return self._index

    async def complete(
        self,
        messages: list[Message],
        *,
        tools: list[dict[str, Any]] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> Completion:
        del tools, temperature, max_tokens
        self.received.append(list(messages))

        if self._index >= len(self._script):
            # An exhausted script is a test error, not model behaviour — so fail loudly
            # instead of silently returning an empty answer.
            raise ProviderError(
                f"Mock script exhausted after {self._index} calls — "
                "the loop needed more iterations than scripted"
            )

        step = self._script[self._index]
        self._index += 1
        completion = step(messages) if callable(step) else step
        return completion.model_copy(update={"model_id": self.model_id})

    async def aclose(self) -> None:
        return None
