"""Nachrichten- und Antworttypen des Agent-Loops.

Bewusst provider-neutral gehalten: OpenRouter spricht das OpenAI-Format, aber der Harness
soll nicht daran kleben. Die Umwandlung passiert ausschließlich im jeweiligen Provider.
"""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class Role(StrEnum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class ToolCall(BaseModel):
    """Ein vom Modell angeforderter Werkzeugaufruf."""

    model_config = ConfigDict(frozen=True)

    id: str
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class Message(BaseModel):
    model_config = ConfigDict(frozen=True)

    role: Role
    content: str | None = None
    tool_calls: list[ToolCall] = Field(default_factory=list)
    # Nur bei role=TOOL: verweist auf die ToolCall.id, die beantwortet wird.
    tool_call_id: str | None = None

    @classmethod
    def system(cls, content: str) -> Message:
        return cls(role=Role.SYSTEM, content=content)

    @classmethod
    def user(cls, content: str) -> Message:
        return cls(role=Role.USER, content=content)

    @classmethod
    def assistant(cls, content: str | None, tool_calls: list[ToolCall] | None = None) -> Message:
        return cls(role=Role.ASSISTANT, content=content, tool_calls=tool_calls or [])

    @classmethod
    def tool_result(cls, tool_call_id: str, content: str) -> Message:
        return cls(role=Role.TOOL, content=content, tool_call_id=tool_call_id)


class Usage(BaseModel):
    """Tokenverbrauch eines einzelnen Modellaufrufs."""

    model_config = ConfigDict(frozen=True)

    prompt_tokens: int = 0
    completion_tokens: int = 0
    reasoning_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    def __add__(self, other: Usage) -> Usage:
        return Usage(
            prompt_tokens=self.prompt_tokens + other.prompt_tokens,
            completion_tokens=self.completion_tokens + other.completion_tokens,
            reasoning_tokens=self.reasoning_tokens + other.reasoning_tokens,
        )


class FinishReason(StrEnum):
    STOP = "stop"
    TOOL_CALLS = "tool_calls"
    LENGTH = "length"
    CONTENT_FILTER = "content_filter"
    OTHER = "other"


class Completion(BaseModel):
    """Antwort eines Modellaufrufs, providerunabhängig."""

    model_config = ConfigDict(frozen=True)

    message: Message
    usage: Usage = Usage()
    finish_reason: FinishReason = FinishReason.STOP
    model_id: str = ""
    # Vom Provider gemeldete Kosten, falls verfügbar. OpenRouter liefert diese Angabe
    # nicht im Chat-Response, deshalb rechnet der Harness normalerweise selbst.
    reported_cost_usd: Decimal | None = None
