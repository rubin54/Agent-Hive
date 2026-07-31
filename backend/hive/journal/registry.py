"""In-process registry of running runs, plus fan-out to live subscribers.

The tricky part is the late joiner: a browser connecting mid-run must receive *every* event
from the beginning and then continue seamlessly. Snapshot-then-subscribe would drop everything
emitted in between; subscribe-then-snapshot would duplicate it.

The order used here is subscribe first, snapshot second, then drop already-seen sequence
numbers while draining. Duplicates are cheap to filter because every event carries a
monotonically increasing ``sequence``; a gap would be invisible and unrecoverable.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import suppress

from ..harness.events import Event

# Bound per subscriber. A browser that stops reading must not let the queue grow without
# limit; dropping the slowest consumer is better than exhausting memory during a sweep.
SUBSCRIBER_QUEUE_SIZE = 1000


class LiveRun:
    """A run currently in flight, with its events and subscribers."""

    def __init__(self, run_id: str) -> None:
        self.run_id = run_id
        self.events: list[Event] = []
        self.finished = False
        self._subscribers: set[asyncio.Queue[Event | None]] = set()

    def publish(self, event: Event) -> None:
        self.events.append(event)
        for queue in list(self._subscribers):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                # The subscriber cannot keep up. Disconnecting it is honest — a client
                # silently missing events would render an incomplete run as complete.
                self._subscribers.discard(queue)

    def finish(self) -> None:
        self.finished = True
        for queue in list(self._subscribers):
            with suppress(asyncio.QueueFull):
                queue.put_nowait(None)

    def subscribe(self) -> asyncio.Queue[Event | None]:
        queue: asyncio.Queue[Event | None] = asyncio.Queue(maxsize=SUBSCRIBER_QUEUE_SIZE)
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[Event | None]) -> None:
        self._subscribers.discard(queue)

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)


class RunRegistry:
    """Holds the live runs of this process.

    Deliberately in-process and not persisted: a server restart ends running runs, and their
    journals stay readable on disk. For a single-user tool that is the right trade — a
    durable job queue would be considerable machinery for no portfolio gain.
    """

    def __init__(self) -> None:
        self._runs: dict[str, LiveRun] = {}

    def create(self, run_id: str) -> LiveRun:
        live = LiveRun(run_id)
        self._runs[run_id] = live
        return live

    def get(self, run_id: str) -> LiveRun | None:
        return self._runs.get(run_id)

    def finish(self, run_id: str) -> None:
        live = self._runs.get(run_id)
        if live is not None:
            live.finish()

    def forget(self, run_id: str) -> None:
        self._runs.pop(run_id, None)

    @property
    def active_ids(self) -> list[str]:
        return [run_id for run_id, live in self._runs.items() if not live.finished]

    async def stream(self, run_id: str, *, after: int = -1) -> AsyncIterator[Event]:
        """Yield all events after ``after``, then live ones until the run finishes.

        Subscribing happens *before* the snapshot is taken, so nothing emitted in between is
        lost. Events already contained in the snapshot are then filtered out by sequence.
        """
        live = self._runs.get(run_id)
        if live is None:
            return

        queue = live.subscribe()
        try:
            last_sent = after
            for event in list(live.events):
                if event.sequence > last_sent:
                    yield event
                    last_sent = event.sequence

            if live.finished:
                return

            while True:
                # None is the sentinel published by finish(); it ends the stream.
                incoming = await queue.get()
                if incoming is None:
                    return
                if incoming.sequence > last_sent:
                    yield incoming
                    last_sent = incoming.sequence
        finally:
            live.unsubscribe(queue)
