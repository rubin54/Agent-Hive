"""Event journal, live registry and the sink that ties them together."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from hive.harness.events import Event, EventType
from hive.journal.registry import SUBSCRIBER_QUEUE_SIZE, RunRegistry
from hive.journal.sink import JournalSink
from hive.journal.store import JournalStore, RunMeta, RunStatus, utc_now


def make_event(sequence: int, run_id: str = "r") -> Event:
    return Event(
        type=EventType.ITERATION_STARTED,
        sequence=sequence,
        run_id=run_id,
        payload={"iteration": sequence},
    )


def make_meta(run_id: str = "r", **kwargs: object) -> RunMeta:
    defaults: dict[str, object] = {"model_id": "acme/model", "started_at": utc_now()}
    defaults.update(kwargs)
    return RunMeta(run_id=run_id, **defaults)  # type: ignore[arg-type]


# ----------------------------------------------------------------------- store


def test_events_round_trip(tmp_path: Path) -> None:
    store = JournalStore(tmp_path)
    store.create(make_meta())
    for i in range(3):
        store.append("r", make_event(i))

    events = store.read_events("r")
    assert [e.sequence for e in events] == [0, 1, 2]
    assert events[0].payload["iteration"] == 0


def test_after_returns_only_the_remainder(tmp_path: Path) -> None:
    """The backfill path for a client that reconnects after a dropped connection."""
    store = JournalStore(tmp_path)
    store.create(make_meta())
    for i in range(5):
        store.append("r", make_event(i))

    assert [e.sequence for e in store.read_events("r", after=2)] == [3, 4]
    assert store.read_events("r", after=99) == []


def test_truncated_last_line_costs_one_event_not_the_run(tmp_path: Path) -> None:
    """A crash mid-write must leave everything before it readable."""
    store = JournalStore(tmp_path)
    store.create(make_meta())
    store.append("r", make_event(0))
    store.append("r", make_event(1))

    journal = tmp_path / "r" / "journal.jsonl"
    with journal.open("a", encoding="utf-8") as handle:
        handle.write('{"type":"iteration_started","sequ')

    assert [e.sequence for e in store.read_events("r")] == [0, 1]


def test_meta_round_trip_and_unknown_fields(tmp_path: Path) -> None:
    """A run written by an older version must stay listable after a schema change."""
    store = JournalStore(tmp_path)
    store.create(make_meta(goal="build something", template_ref="counter-page@1"))

    path = tmp_path / "r" / "meta.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["field_from_the_future"] = 42
    path.write_text(json.dumps(payload), encoding="utf-8")

    meta = store.read_meta("r")
    assert meta is not None
    assert meta.goal == "build something"
    assert meta.template_ref == "counter-page@1"
    assert meta.status is RunStatus.RUNNING


def test_meta_is_written_atomically(tmp_path: Path) -> None:
    """A reader must never catch a half-written meta file."""
    store = JournalStore(tmp_path)
    store.create(make_meta())
    assert not list((tmp_path / "r").glob("*.partial"))


def test_corrupt_meta_is_skipped_not_fatal(tmp_path: Path) -> None:
    (tmp_path / "broken").mkdir(parents=True)
    (tmp_path / "broken" / "meta.json").write_text("not json", encoding="utf-8")
    store = JournalStore(tmp_path)
    store.create(make_meta("good"))

    assert [m.run_id for m in store.list_runs()] == ["good"]


def test_list_runs_is_newest_first(tmp_path: Path) -> None:
    store = JournalStore(tmp_path)
    store.create(make_meta("old", started_at="2026-01-01T00:00:00+00:00"))
    store.create(make_meta("new", started_at="2026-06-01T00:00:00+00:00"))

    assert [m.run_id for m in store.list_runs()] == ["new", "old"]


def test_costs_are_stored_as_strings(tmp_path: Path) -> None:
    """JSON floats would reintroduce exactly the rounding the backend avoids."""
    store = JournalStore(tmp_path)
    store.create(make_meta(cost_usd="0.00000014"))
    raw = json.loads((tmp_path / "r" / "meta.json").read_text(encoding="utf-8"))
    assert raw["cost_usd"] == "0.00000014"
    assert isinstance(raw["cost_usd"], str)


# -------------------------------------------------------------------- registry


async def test_late_joiner_receives_backlog_then_live_events() -> None:
    registry = RunRegistry()
    live = registry.create("r")
    for i in range(3):
        live.publish(make_event(i))

    received: list[int] = []

    async def consume() -> None:
        async for event in registry.stream("r"):
            received.append(event.sequence)
            if len(received) == 6:
                break

    task = asyncio.create_task(consume())
    await asyncio.sleep(0.05)  # let the consumer subscribe and drain the backlog
    for i in range(3, 6):
        live.publish(make_event(i))

    await asyncio.wait_for(task, timeout=2)
    assert received == [0, 1, 2, 3, 4, 5]


async def test_events_arriving_during_backlog_are_not_lost_or_duplicated() -> None:
    """The exact interleaving the subscribe-then-snapshot order exists for.

    Snapshot-then-subscribe would drop anything emitted in between; subscribing first and
    filtering by sequence makes both a gap and a duplicate impossible.
    """
    registry = RunRegistry()
    live = registry.create("r")
    live.publish(make_event(0))
    live.publish(make_event(1))

    stream = registry.stream("r")
    first = await anext(stream)  # subscribes, then takes the snapshot
    assert first.sequence == 0

    # Arrives after subscription and lands in both the queue and the snapshot list.
    live.publish(make_event(2))

    assert (await anext(stream)).sequence == 1
    assert (await anext(stream)).sequence == 2

    live.finish()
    with pytest.raises(StopAsyncIteration):
        await anext(stream)


async def test_after_skips_already_seen_events() -> None:
    registry = RunRegistry()
    live = registry.create("r")
    for i in range(4):
        live.publish(make_event(i))
    live.finish()

    seen = [event.sequence async for event in registry.stream("r", after=1)]
    assert seen == [2, 3]


async def test_finished_run_stream_ends_immediately() -> None:
    registry = RunRegistry()
    live = registry.create("r")
    live.publish(make_event(0))
    live.finish()

    assert [e.sequence async for e in registry.stream("r")] == [0]


async def test_unknown_run_yields_nothing() -> None:
    registry = RunRegistry()
    assert [e async for e in registry.stream("nope")] == []


def test_slow_subscriber_is_dropped_rather_than_growing_unbounded() -> None:
    """A client that stops reading must not exhaust memory during a sweep."""
    registry = RunRegistry()
    live = registry.create("r")
    live.subscribe()
    assert live.subscriber_count == 1

    for i in range(SUBSCRIBER_QUEUE_SIZE + 5):
        live.publish(make_event(i))

    assert live.subscriber_count == 0


def test_subscribers_are_removed_on_unsubscribe() -> None:
    registry = RunRegistry()
    live = registry.create("r")
    queue = live.subscribe()
    live.unsubscribe(queue)
    assert live.subscriber_count == 0


# ------------------------------------------------------------------------ sink


def test_sink_assigns_sequences_persists_and_broadcasts(tmp_path: Path) -> None:
    store = JournalStore(tmp_path)
    store.create(make_meta())
    registry = RunRegistry()
    live = registry.create("r")
    queue = live.subscribe()

    sink = JournalSink(store, "r", live)
    sink.emit(Event(type=EventType.RUN_STARTED))
    sink.emit(Event(type=EventType.ITERATION_STARTED))

    # in memory, on disk and on the wire — all three from one emit
    assert [e.sequence for e in sink.events] == [0, 1]
    assert [e.sequence for e in store.read_events("r")] == [0, 1]
    assert queue.qsize() == 2


def test_sink_works_without_a_live_run(tmp_path: Path) -> None:
    """CLI runs have no subscribers; persistence must not depend on them."""
    store = JournalStore(tmp_path)
    store.create(make_meta())
    sink = JournalSink(store, "r")
    sink.emit(Event(type=EventType.RUN_STARTED))

    assert len(store.read_events("r")) == 1
