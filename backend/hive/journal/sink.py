"""Event sink that persists and broadcasts in one step.

Drop-in replacement for ``MemorySink``: same interface, same in-memory list, plus a line in
the journal and a push to live subscribers. The agent loop knows nothing about either — it
only ever calls ``emit``.
"""

from __future__ import annotations

from ..harness.events import Event
from .registry import LiveRun
from .store import JournalStore


class JournalSink:
    """Assigns sequence numbers, appends to the journal, notifies subscribers."""

    def __init__(self, store: JournalStore, run_id: str, live: LiveRun | None = None) -> None:
        self._store = store
        self._live = live
        self.run_id = run_id
        self.events: list[Event] = []

    def emit(self, event: Event) -> None:
        event.sequence = len(self.events)
        event.run_id = self.run_id
        self.events.append(event)

        # Written synchronously. The append is a few hundred bytes while the surrounding
        # loop waits on model calls and Docker for seconds — the ordering guarantee is worth
        # more here than saving microseconds.
        self._store.append(self.run_id, event)

        if self._live is not None:
            self._live.publish(event)
