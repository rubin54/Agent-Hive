"""Catalog endpoints for the dashboard."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from ...catalog import (
    CatalogFetchError,
    CatalogFilter,
    CatalogPage,
    CatalogService,
    CatalogUnavailableError,
    ProviderFacet,
    Role,
    SortKey,
    apply_filter,
    paginate,
    provider_facets,
    to_summary,
)
from ..deps import get_catalog_service

router = APIRouter(prefix="/catalog", tags=["catalog"])

ServiceDep = Annotated[CatalogService, Depends(get_catalog_service)]


class SnapshotInfo(BaseModel):
    snapshot_id: str
    synced_at: str
    source: str
    model_count: int
    is_fixture: bool = False


class CatalogStatus(BaseModel):
    """Where the data currently being served comes from.

    ``is_fixture=True`` means: never synced, running on the bundled state. The dashboard
    points that out instead of presenting stale prices as current.
    """

    snapshot_id: str
    synced_at: str
    source: str
    model_count: int
    is_fixture: bool
    tool_capable_count: int
    vision_capable_count: int


def _current(service: CatalogService):  # type: ignore[no-untyped-def]
    try:
        return service.current()
    except CatalogUnavailableError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc


@router.get("/status", response_model=CatalogStatus)
def catalog_status(service: ServiceDep) -> CatalogStatus:
    state = _current(service)
    summaries = [to_summary(m) for m in state.models]
    return CatalogStatus(
        snapshot_id=state.snapshot.snapshot_id,
        synced_at=state.snapshot.synced_at.isoformat(),
        source=state.snapshot.source,
        model_count=len(summaries),
        is_fixture=state.is_fixture,
        tool_capable_count=sum(1 for s in summaries if s.supports_tools),
        vision_capable_count=sum(1 for s in summaries if s.supports_vision),
    )


@router.get("/models", response_model=CatalogPage)
def list_models(
    service: ServiceDep,
    search: Annotated[str | None, Query(max_length=200)] = None,
    provider: str | None = None,
    role: Role | None = None,
    supports_tools: bool | None = None,
    supports_vision: bool | None = None,
    free_only: bool = False,
    max_blended_usd_per_mtok: Annotated[float | None, Query(ge=0)] = None,
    min_context_length: Annotated[int | None, Query(ge=0)] = None,
    sort: SortKey = SortKey.NAME,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=500)] = 60,
) -> CatalogPage:
    state = _current(service)
    criteria = CatalogFilter(
        search=search,
        provider=provider,
        role=role,
        supports_tools=supports_tools,
        supports_vision=supports_vision,
        free_only=free_only,
        max_blended_usd_per_mtok=max_blended_usd_per_mtok,
        min_context_length=min_context_length,
        sort=sort,
    )
    matched = apply_filter(state.models, criteria)
    items, total = paginate(matched, offset=offset, limit=limit)
    return CatalogPage(
        snapshot_id=state.snapshot.snapshot_id,
        synced_at=state.snapshot.synced_at.isoformat(),
        total=total,
        offset=offset,
        limit=limit,
        items=items,
    )


@router.get("/providers", response_model=list[ProviderFacet])
def list_providers(service: ServiceDep) -> list[ProviderFacet]:
    return provider_facets(_current(service).models)


@router.get("/snapshots", response_model=list[SnapshotInfo])
def list_snapshots(service: ServiceDep) -> list[SnapshotInfo]:
    infos: list[SnapshotInfo] = []
    for snapshot_id in service.snapshot_ids():
        snapshot = service.load(snapshot_id)
        if snapshot is None:
            continue
        infos.append(
            SnapshotInfo(
                snapshot_id=snapshot.snapshot_id,
                synced_at=snapshot.synced_at.isoformat(),
                source=snapshot.source,
                model_count=snapshot.model_count,
            )
        )
    return infos


@router.post("/sync", response_model=SnapshotInfo, status_code=status.HTTP_201_CREATED)
async def sync_catalog(service: ServiceDep) -> SnapshotInfo:
    try:
        snapshot = await service.sync()
    except CatalogFetchError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc
    return SnapshotInfo(
        snapshot_id=snapshot.snapshot_id,
        synced_at=snapshot.synced_at.isoformat(),
        source=snapshot.source,
        model_count=snapshot.model_count,
    )
