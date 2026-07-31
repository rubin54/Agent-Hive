"""Run endpoints and the live stream.

The runs here use the mock provider but a real Docker sandbox, so they are marked accordingly
and skip themselves without a daemon. The pure API behaviour — listing, backfill, 404s — is
tested against a pre-written journal and needs no container.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from hive.harness.events import Event, EventType
from hive.journal.registry import RunRegistry
from hive.journal.store import JournalStore, RunMeta, RunStatus, utc_now
from hive.runs.service import RunRequest, RunRequestError, RunService

from .test_sandbox import requires_docker

REPO = Path(__file__).resolve().parents[2]


def build_service(tmp_path: Path) -> RunService:
    from hive.api.deps import get_catalog_service
    from hive.templates.store import TemplateStore

    return RunService(
        store=JournalStore(tmp_path / "runs"),
        registry=RunRegistry(),
        templates=TemplateStore(REPO / "templates"),
        catalog=get_catalog_service(),
        screenshot_root=tmp_path / "screenshots",
    )


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    from hive.api.app import create_app
    from hive.api.deps import get_run_service

    service = build_service(tmp_path)
    app = create_app()
    app.dependency_overrides[get_run_service] = lambda: service

    # Used as a context manager on purpose: only then does TestClient keep one event loop
    # alive across requests. Without it every request gets a fresh portal and a background
    # run started by one request is orphaned before the next can observe it.
    with TestClient(app) as test_client:
        test_client.service = service  # type: ignore[attr-defined]
        yield test_client


def seed_finished_run(service: RunService, run_id: str = "seeded") -> None:
    """Write a completed run straight to disk — no container needed."""
    store = service.store
    store.create(
        RunMeta(
            run_id=run_id,
            model_id="acme/model",
            started_at=utc_now(),
            status=RunStatus.COMPLETED,
            finished_at=utc_now(),
            goal="do a thing",
            iterations=2,
            prompt_tokens=100,
            completion_tokens=50,
            cost_usd="0.00042",
            stop_reason="completed",
        )
    )
    for i in range(4):
        store.append(run_id, Event(type=EventType.ITERATION_STARTED, sequence=i, run_id=run_id))


# ------------------------------------------------------------------- read side


def test_listing_is_empty_before_any_run(client: TestClient) -> None:
    assert client.get("/api/runs").json() == []


def test_run_summary_exposes_cost_as_string(client: TestClient) -> None:
    """Costs are Decimal all the way — a JSON float would undo that."""
    seed_finished_run(client.service)  # type: ignore[attr-defined]

    body = client.get("/api/runs/seeded").json()
    assert body["cost_usd"] == "0.00042"
    assert isinstance(body["cost_usd"], str)
    assert body["total_tokens"] == 150
    assert body["live"] is False


def test_events_endpoint_supports_backfill(client: TestClient) -> None:
    seed_finished_run(client.service)  # type: ignore[attr-defined]

    everything = client.get("/api/runs/seeded/events").json()
    assert [e["sequence"] for e in everything["events"]] == [0, 1, 2, 3]

    remainder = client.get("/api/runs/seeded/events", params={"after": 1}).json()
    assert [e["sequence"] for e in remainder["events"]] == [2, 3]


def test_run_stuck_on_running_is_reported_as_abandoned(client: TestClient) -> None:
    """Runs live in this process — a restart leaves metadata promising progress forever.

    Reporting that honestly is better than a list entry that spins indefinitely, so the state
    is corrected on read and written back.
    """
    service: RunService = client.service  # type: ignore[attr-defined]
    service.store.create(RunMeta(run_id="orphan", model_id="acme/model", started_at=utc_now()))

    body = client.get("/api/runs/orphan").json()
    assert body["status"] == "failed"
    assert body["stop_reason"] == "abandoned"
    assert body["live"] is False

    # And it is persisted, not just patched on the way out.
    assert service.store.read_meta("orphan").status is RunStatus.FAILED  # type: ignore[union-attr]


def test_unknown_run_is_404(client: TestClient) -> None:
    assert client.get("/api/runs/nope").status_code == 404
    assert client.get("/api/runs/nope/events").status_code == 404


def test_screenshot_path_traversal_is_refused(client: TestClient, tmp_path: Path) -> None:
    """The name is a file name, never a path — otherwise this endpoint reads any file."""
    service: RunService = client.service  # type: ignore[attr-defined]
    assert service.screenshot_path("seeded", "../../../etc/passwd") is None
    assert service.screenshot_path("seeded", "sub/shot.png") is None
    assert service.screenshot_path("seeded", ".hidden") is None


def test_websocket_replays_a_finished_run(client: TestClient) -> None:
    """A finished run streams straight from the journal — same events, same order."""
    seed_finished_run(client.service)  # type: ignore[attr-defined]

    with client.websocket_connect("/api/runs/seeded/stream") as socket:
        sequences = []
        while True:
            message = json.loads(socket.receive_text())
            if message.get("type") == "stream_closed":
                break
            sequences.append(message["sequence"])

    assert sequences == [0, 1, 2, 3]


def test_websocket_honours_after(client: TestClient) -> None:
    seed_finished_run(client.service)  # type: ignore[attr-defined]

    with client.websocket_connect("/api/runs/seeded/stream?after=2") as socket:
        first = json.loads(socket.receive_text())
    assert first["sequence"] == 3


def test_websocket_rejects_unknown_run(client: TestClient) -> None:
    """The socket closes with a dedicated code instead of streaming an empty run."""
    from starlette.websockets import WebSocketDisconnect

    with (
        client.websocket_connect("/api/runs/nope/stream") as socket,
        pytest.raises(WebSocketDisconnect) as exc,
    ):
        socket.receive_text()
    assert exc.value.code == 4404


# ------------------------------------------------------------------ validation


def test_request_without_goal_or_template_is_rejected(tmp_path: Path) -> None:
    service = build_service(tmp_path)
    with pytest.raises(RunRequestError, match="template or goal"):
        service.start(RunRequest(model_id="acme/model", provider="mock"))


def test_unknown_template_is_rejected(tmp_path: Path) -> None:
    service = build_service(tmp_path)
    with pytest.raises(RunRequestError, match="not found"):
        service.start(RunRequest(model_id="a/b", template_name="nope", provider="mock"))


def test_missing_api_key_is_rejected_before_anything_runs(tmp_path: Path) -> None:
    service = build_service(tmp_path)
    with pytest.raises(RunRequestError, match="API key"):
        service.start(RunRequest(model_id="a/b", goal="x", provider="openrouter"))


def test_start_via_api_reports_the_error(client: TestClient) -> None:
    response = client.post("/api/runs", json={"model_id": "a/b", "provider": "openrouter"})
    assert response.status_code == 400


@requires_docker
def test_start_over_http_actually_launches(client: TestClient) -> None:
    """The happy path through HTTP, not just through the service.

    This gap let a real bug through: the endpoint was ``def`` instead of ``async def``, so
    FastAPI ran it in the threadpool where there is no event loop and the background task
    could never be created. Every service-level test passed because they were already async.
    """
    import time

    response = client.post(
        "/api/runs",
        json={"template_name": "counter-page", "provider": "mock", "model_id": ""},
    )
    assert response.status_code == 201, response.text
    run_id = response.json()["run_id"]

    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        body = client.get(f"/api/runs/{run_id}").json()
        if not body["live"] and body["status"] != "running":
            break
        time.sleep(0.5)

    assert body["status"] == "completed"
    assert body["checks_passed"] is True
    assert client.get(f"/api/runs/{run_id}/events").json()["events"]


# ------------------------------------------------------------------- live runs


@requires_docker
async def test_run_is_journalled_end_to_end(tmp_path: Path) -> None:
    """A real run: container, tools, checks — and a journal that survives it."""
    service = build_service(tmp_path)
    meta = service.start(
        RunRequest(model_id="mock/counter-page", template_name="counter-page", provider="mock")
    )
    await service.wait(meta.run_id)

    final = service.get(meta.run_id)
    assert final is not None
    assert final.status is RunStatus.COMPLETED
    assert final.stop_reason == "completed"
    assert final.iterations > 0
    assert final.template_ref == "counter-page@1"
    assert final.checks_passed is True
    assert [c["name"] for c in final.check_summary] == [
        "files-present",
        "syntax",
        "serve",
        "behaviour",
    ]
    assert final.screenshots

    # The journal on disk is complete and consistent with the run.
    events = JournalStore(tmp_path / "runs").read_events(meta.run_id)
    assert [e.sequence for e in events] == list(range(len(events)))
    assert events[0].type is EventType.RUN_STARTED
    assert events[-1].type is EventType.RUN_FINISHED

    # Screenshots landed under the run, not in a shared directory.
    assert list((tmp_path / "screenshots" / meta.run_id).glob("*.png"))


@requires_docker
async def test_live_stream_sees_events_while_the_run_is_in_flight(tmp_path: Path) -> None:
    """The point of the whole milestone: watching, not polling after the fact."""
    import asyncio

    service = build_service(tmp_path)
    meta = service.start(
        RunRequest(model_id="mock/demo-scripted", goal="build a counter page", provider="mock")
    )

    seen: list[str] = []

    async def watch() -> None:
        async for event in service.stream(meta.run_id):
            seen.append(event.type.value)

    watcher = asyncio.create_task(watch())
    await service.wait(meta.run_id)
    await asyncio.wait_for(watcher, timeout=10)

    assert seen[0] == "run_started"
    assert seen[-1] == "run_finished"
    assert "tool_returned" in seen
    # No gaps: a live viewer must see exactly what the journal recorded.
    assert len(seen) == len(JournalStore(tmp_path / "runs").read_events(meta.run_id))
