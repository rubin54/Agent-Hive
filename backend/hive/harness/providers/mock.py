"""Deterministischer Mock-Provider.

Grundlage für Tests, CI und die schlüsselfertige Demo: Der Harness lässt sich damit
vollständig durchspielen — echte Sandbox, echte Werkzeuge, echte Dateien — ohne einen
einzigen API-Aufruf. Ohne dieses Stück wäre weder eine Regressionsprüfung noch ein
`make demo` ohne Key möglich.

Ab M9 kommt daneben ein Replay-Provider, der aufgezeichnete echte Läufe abspielt.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from ..messages import Completion, FinishReason, Message, ToolCall, Usage
from .base import ProviderError

# Ein Skript kann statt fester Antworten auch eine Funktion sein, die auf den bisherigen
# Verlauf reagiert — damit lassen sich Nachbesserungsschleifen nachstellen.
ScriptStep = Completion | Callable[[list[Message]], Completion]


def say(content: str, *, prompt_tokens: int = 100, completion_tokens: int = 20) -> Completion:
    """Abschließende Textantwort."""
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
    """Einzelner Werkzeugaufruf."""
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
    """Mehrere Werkzeuge in einer Antwort — bildet parallele Tool-Calls ab."""
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
    """Spielt ein festes Skript ab. Jeder Aufruf verbraucht einen Schritt."""

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
            # Ein erschöpftes Skript ist ein Testfehler, kein Modellverhalten — deshalb
            # laut scheitern statt still eine leere Antwort zu liefern.
            raise ProviderError(
                f"Mock-Skript erschöpft nach {self._index} Aufrufen — "
                "der Loop hat mehr Iterationen gebraucht als vorgesehen"
            )

        step = self._script[self._index]
        self._index += 1
        completion = step(messages) if callable(step) else step
        return completion.model_copy(update={"model_id": self.model_id})

    async def aclose(self) -> None:
        return None
