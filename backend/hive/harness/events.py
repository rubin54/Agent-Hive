"""Events of the agent loop.

Every state transition is an event. In M1 they only land in an in-memory sink or on the
console — from M3 the same sink writes to the journal, feeds the WebSocket stream and carries
replay and cost accounting. That is why they are created complete and serialisable now rather
than being retrofitted later.
"""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
from typing import Any, Protocol

from pydantic import BaseModel, Field

from .messages import ToolCall, Usage


class EventType(StrEnum):
    RUN_STARTED = "run_started"
    ITERATION_STARTED = "iteration_started"
    MODEL_CALLED = "model_called"
    MODEL_RESPONDED = "model_responded"
    TOOL_CALLED = "tool_called"
    TOOL_RETURNED = "tool_returned"
    RUN_FINISHED = "run_finished"


class StopReason(StrEnum):
    COMPLETED = "completed"
    BUDGET = "budget"
    TOOL_ERROR_LIMIT = "tool_error_limit"
    PROVIDER_ERROR = "provider_error"


class Event(BaseModel):
    """Base of all events. ``sequence`` is assigned by the sink."""

    type: EventType
    sequence: int = 0
    run_id: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)


class EventSink(Protocol):
    def emit(self, event: Event) -> None: ...


class MemorySink:
    """Collects events in memory — the basis for tests and CLI output."""

    def __init__(self, run_id: str = "") -> None:
        self.run_id = run_id
        self.events: list[Event] = []

    def emit(self, event: Event) -> None:
        event.sequence = len(self.events)
        event.run_id = self.run_id
        self.events.append(event)

    def of_type(self, event_type: EventType) -> list[Event]:
        return [e for e in self.events if e.type is event_type]


# ------------------------------------------------------------------ constructors


def run_started(*, model_id: str, goal: str, tools: list[str]) -> Event:
    return Event(
        type=EventType.RUN_STARTED,
        payload={"model_id": model_id, "goal": goal, "tools": tools},
    )


def iteration_started(*, iteration: int) -> Event:
    return Event(type=EventType.ITERATION_STARTED, payload={"iteration": iteration})


def model_called(*, iteration: int, message_count: int) -> Event:
    return Event(
        type=EventType.MODEL_CALLED,
        payload={"iteration": iteration, "message_count": message_count},
    )


def model_responded(
    *,
    iteration: int,
    usage: Usage,
    cost_usd: Decimal,
    finish_reason: str,
    tool_calls: list[ToolCall],
) -> Event:
    return Event(
        type=EventType.MODEL_RESPONDED,
        payload={
            "iteration": iteration,
            "usage": usage.model_dump(),
            "cost_usd": str(cost_usd),
            "finish_reason": finish_reason,
            "tool_calls": [c.name for c in tool_calls],
        },
    )


def tool_called(*, iteration: int, call: ToolCall) -> Event:
    return Event(
        type=EventType.TOOL_CALLED,
        payload={"iteration": iteration, "name": call.name, "arguments": call.arguments},
    )


def tool_returned(*, iteration: int, name: str, ok: bool, result: str) -> Event:
    # Tool output can get very large (directory listings, build logs). The event carries a
    # shortened form; the full text still goes to the model as a message.
    preview = result if len(result) <= 2000 else result[:2000] + f"… [{len(result)} chars]"
    return Event(
        type=EventType.TOOL_RETURNED,
        payload={"iteration": iteration, "name": name, "ok": ok, "result": preview},
    )


def run_finished(*, reason: StopReason, detail: str, iterations: int, cost_usd: Decimal) -> Event:
    return Event(
        type=EventType.RUN_FINISHED,
        payload={
            "reason": reason.value,
            "detail": detail,
            "iterations": iterations,
            "cost_usd": str(cost_usd),
        },
    )
