"""Append-only event journal on disk.

One directory per run:

```
data/runs/<run_id>/
    meta.json        run metadata, rewritten on status changes
    journal.jsonl    one event per line, append-only, never rewritten
```

JSONL rather than a single JSON document is deliberate: events are appended while the run is
in flight, and a crash must leave everything written so far intact and readable. A truncated
last line costs one event, not the whole run.

The journal is the foundation the plan builds on — the WebSocket stream is this event stream,
replay is re-reading it, and cost accounting is an aggregation over it. From M7 the swarm
metrics are analyses of the very same lines.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from pathlib import Path
from typing import Any

from ..harness.events import Event

META_FILE = "meta.json"
JOURNAL_FILE = "journal.jsonl"


class RunStatus(StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass(slots=True)
class RunMeta:
    """Everything needed to list a run without reading its events."""

    run_id: str
    model_id: str
    started_at: str
    status: RunStatus = RunStatus.RUNNING
    finished_at: str | None = None
    goal: str = ""
    template_ref: str | None = None
    template_hash: str | None = None
    provider: str = "openrouter"

    iterations: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: str = "0"
    pricing_known: bool = False

    stop_reason: str | None = None
    detail: str | None = None
    checks_passed: bool | None = None
    check_summary: list[dict[str, Any]] = field(default_factory=list)
    screenshots: list[str] = field(default_factory=list)
    workspace: str = ""

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    def to_json(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["status"] = self.status.value
        return payload

    @classmethod
    def from_json(cls, payload: dict[str, Any]) -> RunMeta:
        known = set(cls.__slots__)
        # Unknown keys are ignored rather than fatal: an older run written by a previous
        # version must stay listable after a schema change.
        data = {k: v for k, v in payload.items() if k in known}
        data["status"] = RunStatus(data.get("status", RunStatus.RUNNING))
        return cls(**data)


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


class JournalStore:
    def __init__(self, root: Path) -> None:
        self.root = root

    def directory(self, run_id: str) -> Path:
        return self.root / run_id

    # ---------------------------------------------------------------- writing

    def create(self, meta: RunMeta) -> None:
        self.directory(meta.run_id).mkdir(parents=True, exist_ok=True)
        self.write_meta(meta)

    def write_meta(self, meta: RunMeta) -> None:
        path = self.directory(meta.run_id) / META_FILE
        path.parent.mkdir(parents=True, exist_ok=True)
        # Write beside and rename: a reader must never catch a half-written meta file.
        temp = path.with_suffix(".partial")
        temp.write_text(json.dumps(meta.to_json(), ensure_ascii=False, indent=2), encoding="utf-8")
        temp.replace(path)

    def append(self, run_id: str, event: Event) -> None:
        path = self.directory(run_id) / JOURNAL_FILE
        path.parent.mkdir(parents=True, exist_ok=True)
        line = event.model_dump_json()
        with path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")

    # ---------------------------------------------------------------- reading

    def read_meta(self, run_id: str) -> RunMeta | None:
        path = self.directory(run_id) / META_FILE
        if not path.is_file():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(payload, dict):
            return None
        try:
            return RunMeta.from_json(payload)
        except (TypeError, ValueError):
            return None

    def read_events(self, run_id: str, *, after: int = -1) -> list[Event]:
        """Events of a run, optionally only those after a sequence number.

        ``after`` exists for late joiners: a browser reconnecting knows the last sequence it
        saw and asks only for the remainder.
        """
        path = self.directory(run_id) / JOURNAL_FILE
        if not path.is_file():
            return []

        events: list[Event] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                event = Event.model_validate_json(line)
            except ValueError:
                # A truncated final line after a crash costs one event, not the run.
                continue
            if event.sequence > after:
                events.append(event)
        return events

    def list_runs(self, *, limit: int = 50) -> list[RunMeta]:
        """Runs, newest first. Directories without readable metadata are skipped."""
        if not self.root.is_dir():
            return []
        metas = [
            meta
            for entry in self.root.iterdir()
            if entry.is_dir() and (meta := self.read_meta(entry.name)) is not None
        ]
        metas.sort(key=lambda m: m.started_at, reverse=True)
        return metas[:limit]

    def delete(self, run_id: str) -> bool:
        directory = self.directory(run_id)
        if not directory.is_dir():
            return False
        for path in sorted(directory.rglob("*"), reverse=True):
            path.unlink() if path.is_file() else path.rmdir()
        directory.rmdir()
        return True


def decimal_to_str(value: Decimal) -> str:
    """Costs travel as strings — JSON floats would reintroduce the rounding we avoid."""
    return str(value)
