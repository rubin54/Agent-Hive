"""The agent loop — the control variable of the benchmark."""

from __future__ import annotations

from decimal import Decimal

from hive.harness.agent import MAX_CONSECUTIVE_TOOL_FAILURES, Agent
from hive.harness.budget import BudgetLimits, BudgetTracker
from hive.harness.events import EventType, MemorySink, StopReason
from hive.harness.messages import Role
from hive.harness.providers.mock import MockProvider, call, calls, say
from hive.harness.tools import ToolRegistry, tool_from_function

CALLS: list[str] = []


async def note(text: str) -> str:
    """Remember a piece of text."""
    CALLS.append(text)
    return f"noted: {text}"


def build(script: list[object], **limits: object) -> tuple[Agent, MemorySink, MockProvider]:
    CALLS.clear()
    defaults: dict[str, object] = {
        "max_iterations": 20,
        "max_tokens": None,
        "max_wall_clock_seconds": None,
        "max_cost_usd": None,
    }
    defaults.update(limits)
    provider = MockProvider(script)  # type: ignore[arg-type]
    sink = MemorySink(run_id="test")
    agent = Agent(
        provider=provider,
        tools=ToolRegistry([tool_from_function(note)]),
        budget=BudgetTracker(limits=BudgetLimits(**defaults)),  # type: ignore[arg-type]
        sink=sink,
    )
    return agent, sink, provider


async def test_loop_runs_tools_then_finishes() -> None:
    agent, sink, _ = build([call("note", {"text": "one"}), say("done")])
    result = await agent.run("Goal")

    assert result.succeeded
    assert result.final_message == "done"
    assert CALLS == ["one"]
    assert sink.events[0].type is EventType.RUN_STARTED
    assert sink.events[-1].type is EventType.RUN_FINISHED


async def test_conversation_shape_is_correct() -> None:
    """Every tool call must be followed by exactly one TOOL message with a matching id."""
    agent, _, _ = build([call("note", {"text": "x"}), say("done")])
    result = await agent.run("Goal")

    roles = [m.role for m in result.messages]
    assert roles[0] is Role.SYSTEM
    assert roles[1] is Role.USER
    assert roles[2] is Role.ASSISTANT
    assert roles[3] is Role.TOOL

    assistant = result.messages[2]
    assert result.messages[3].tool_call_id == assistant.tool_calls[0].id


async def test_parallel_tool_calls_are_all_answered() -> None:
    agent, _, _ = build([calls([("note", {"text": "a"}), ("note", {"text": "b"})]), say("done")])
    result = await agent.run("Goal")

    assert CALLS == ["a", "b"]
    tool_messages = [m for m in result.messages if m.role is Role.TOOL]
    assert len(tool_messages) == 2


async def test_budget_stops_the_loop() -> None:
    # The script would run forever; only the limit ends it.
    agent, sink, provider = build([call("note", {"text": "x"})] * 10, max_iterations=3)
    result = await agent.run("Goal")

    assert result.stop_reason is StopReason.BUDGET
    assert "Iteration limit" in result.detail
    assert provider.calls_made == 3
    assert sink.events[-1].payload["reason"] == "budget"


async def test_repeated_tool_failures_abort_the_run() -> None:
    """Without this rip cord a weak model gets stuck on the same error."""
    agent, _, _ = build([call("nonexistent", {})] * 20)
    result = await agent.run("Goal")

    assert result.stop_reason is StopReason.TOOL_ERROR_LIMIT
    assert str(MAX_CONSECUTIVE_TOOL_FAILURES) in result.detail


async def test_a_single_success_resets_the_failure_counter() -> None:
    script = [call("nonexistent", {})] * 4 + [call("note", {"text": "ok"})]
    script += [call("nonexistent", {})] * 4 + [say("done")]
    agent, _, _ = build(script)
    result = await agent.run("Goal")

    assert result.succeeded
    assert CALLS == ["ok"]


async def test_provider_error_ends_run_without_raising() -> None:
    # An empty script makes the mock fail on the very first call.
    agent, sink, _ = build([])
    result = await agent.run("Goal")

    assert result.stop_reason is StopReason.PROVIDER_ERROR
    assert sink.events[-1].type is EventType.RUN_FINISHED


async def test_events_cover_every_transition() -> None:
    agent, sink, _ = build([call("note", {"text": "x"}), say("done")])
    await agent.run("Goal")

    types = [e.type for e in sink.events]
    for expected in (
        EventType.RUN_STARTED,
        EventType.ITERATION_STARTED,
        EventType.MODEL_CALLED,
        EventType.MODEL_RESPONDED,
        EventType.TOOL_CALLED,
        EventType.TOOL_RETURNED,
        EventType.RUN_FINISHED,
    ):
        assert expected in types

    # Consecutive and gapless — from M3 this exact sequence carries replay and the journal.
    assert [e.sequence for e in sink.events] == list(range(len(sink.events)))


async def test_large_tool_output_is_truncated_in_events() -> None:
    """Events must not be inflated by build logs."""

    async def spew(size: int) -> str:
        """Produce a lot of text."""
        return "x" * size

    provider = MockProvider([call("spew", {"size": 50_000}), say("done")])
    sink = MemorySink()
    agent = Agent(
        provider=provider,
        tools=ToolRegistry([tool_from_function(spew)]),
        budget=BudgetTracker(limits=BudgetLimits(max_tokens=None, max_cost_usd=None)),
        sink=sink,
    )
    result = await agent.run("Goal")

    event = sink.of_type(EventType.TOOL_RETURNED)[0]
    assert len(event.payload["result"]) < 2_200

    # The model receives the full text — only the recording is shortened.
    tool_message = next(m for m in result.messages if m.role is Role.TOOL)
    assert tool_message.content is not None
    assert len(tool_message.content) == 50_000


async def test_cost_is_tracked_per_call() -> None:
    from hive.catalog.models import Pricing

    provider = MockProvider([say("done", prompt_tokens=1000, completion_tokens=500)])
    sink = MemorySink()
    agent = Agent(
        provider=provider,
        tools=ToolRegistry(),
        budget=BudgetTracker(
            limits=BudgetLimits(max_cost_usd=None),
            pricing=Pricing.model_validate({"prompt": "0.000001", "completion": "0.000002"}),
        ),
        sink=sink,
    )
    result = await agent.run("Goal")

    assert result.cost_usd == Decimal("0.002")  # 1000*1e-6 + 500*2e-6
    assert sink.of_type(EventType.MODEL_RESPONDED)[0].payload["cost_usd"] == "0.002000"
