"""Run endpoints: start, list, read, and the live event stream."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from ...harness.events import Event
from ...journal.store import RunMeta
from ...runs.service import RunRequest, RunRequestError, RunService
from ..deps import get_run_service

router = APIRouter(prefix="/runs", tags=["runs"])

ServiceDep = Annotated[RunService, Depends(get_run_service)]


class StartRunRequest(BaseModel):
    model_id: str = ""
    template_name: str | None = None
    goal: str | None = None
    #: "openrouter" for real calls, "mock" for the recorded example run.
    provider: str = "openrouter"
    #: Passed through to OpenRouter and never persisted. The public demo runs on recordings.
    api_key: str = ""


class CheckSummary(BaseModel):
    name: str
    passed: bool
    required: bool
    duration_seconds: float
    detail: str = ""


class RunSummary(BaseModel):
    """Everything the run list and the header of the detail view need."""

    run_id: str
    model_id: str
    status: str
    started_at: str
    finished_at: str | None = None
    goal: str = ""
    template_ref: str | None = None
    template_hash: str | None = None
    provider: str = "openrouter"

    iterations: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    #: A string, not a float — costs are Decimal all the way and JSON floats would
    #: reintroduce exactly the rounding the backend avoids.
    cost_usd: str = "0"
    pricing_known: bool = False

    stop_reason: str | None = None
    detail: str | None = None
    checks_passed: bool | None = None
    check_summary: list[CheckSummary] = Field(default_factory=list)
    screenshots: list[str] = Field(default_factory=list)
    workspace: str = ""
    live: bool = False


class EventPage(BaseModel):
    run_id: str
    events: list[Event]
    live: bool


def _to_summary(meta: RunMeta, *, live: bool) -> RunSummary:
    payload: dict[str, Any] = meta.to_json()
    payload["total_tokens"] = meta.total_tokens
    payload["live"] = live
    return RunSummary.model_validate(payload)


@router.post("", response_model=RunSummary, status_code=status.HTTP_201_CREATED)
async def start_run(body: StartRunRequest, service: ServiceDep) -> RunSummary:
    """Launch a run and return immediately.

    Deliberately ``async``: a sync endpoint would be executed in FastAPI's threadpool, where
    there is no running event loop and the background task could not be created at all.
    """
    try:
        meta = service.start(
            RunRequest(
                model_id=body.model_id,
                template_name=body.template_name,
                goal=body.goal,
                provider=body.provider,
                api_key=body.api_key,
            )
        )
    except RunRequestError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return _to_summary(meta, live=True)


@router.get("", response_model=list[RunSummary])
def list_runs(
    service: ServiceDep,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[RunSummary]:
    return [
        _to_summary(meta, live=service.is_live(meta.run_id))
        for meta in service.list_runs(limit=limit)
    ]


@router.get("/{run_id}", response_model=RunSummary)
def get_run(run_id: str, service: ServiceDep) -> RunSummary:
    meta = service.get(run_id)
    if meta is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Run '{run_id}' not found")
    return _to_summary(meta, live=service.is_live(run_id))


@router.get("/{run_id}/events", response_model=EventPage)
def get_events(
    run_id: str,
    service: ServiceDep,
    after: Annotated[int, Query(ge=-1)] = -1,
) -> EventPage:
    """Recorded events, optionally only those after a sequence number.

    This is the fallback for clients that cannot use WebSockets, and the backfill path after
    a dropped connection.
    """
    if service.get(run_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Run '{run_id}' not found")
    return EventPage(
        run_id=run_id, events=service.events(run_id, after=after), live=service.is_live(run_id)
    )


@router.get("/{run_id}/screenshots/{name}")
def get_screenshot(run_id: str, name: str, service: ServiceDep) -> FileResponse:
    path = service.screenshot_path(run_id, name)
    if path is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Screenshot not found")
    return FileResponse(path, media_type="image/png")


@router.websocket("/{run_id}/stream")
async def stream_run(websocket: WebSocket, run_id: str, service: ServiceDep) -> None:
    """Live event stream.

    The same events as the REST endpoint, only pushed. There is no separate code path for the
    live UI — the stream *is* the event stream, which is what makes replay and live view the
    same thing.
    """
    await websocket.accept()

    after = -1
    raw_after = websocket.query_params.get("after")
    if raw_after is not None:
        try:
            after = int(raw_after)
        except ValueError:
            after = -1

    if service.get(run_id) is None:
        await websocket.close(code=4404, reason="run not found")
        return

    try:
        async for event in service.stream(run_id, after=after):
            await websocket.send_text(event.model_dump_json())
        # A closing frame tells the client the run is over, so it can stop reconnecting.
        await websocket.send_text('{"type":"stream_closed"}')
    except WebSocketDisconnect:
        return
    finally:
        if websocket.client_state.name == "CONNECTED":
            await websocket.close()
