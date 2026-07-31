"""Snapshot storage and the HTTP interface."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from hive.catalog import (
    CatalogService,
    CatalogStore,
    CatalogUnavailableError,
    OpenRouterModel,
)
from hive.catalog.client import CatalogFetchError, fetch_models

from .conftest import make_model

MODELS_URL = "https://openrouter.ai/api/v1/models"


# ----------------------------------------------------------------------- store


def test_snapshots_are_immutable_and_ordered(tmp_path: Path) -> None:
    store = CatalogStore(tmp_path)
    older = store.save(
        [make_model("a/one")],
        [{"id": "a/one", "name": "one"}],
        source=MODELS_URL,
        synced_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    newer = store.save(
        [make_model("a/one"), make_model("b/two")],
        [{"id": "a/one", "name": "one"}, {"id": "b/two", "name": "two"}],
        source=MODELS_URL,
        synced_at=datetime(2026, 6, 1, tzinfo=UTC),
    )

    assert store.list_snapshot_ids() == [newer.snapshot_id, older.snapshot_id]

    # The old state survives unchanged — otherwise older results could no longer be traced
    # back to the prices they were produced under.
    revived = store.load(older.snapshot_id)
    assert revived is not None
    assert revived.model_count == 1
    assert store.load_latest() is not None
    assert store.load_latest().model_count == 2  # type: ignore[union-attr]


def test_partial_write_leaves_no_usable_snapshot(tmp_path: Path) -> None:
    store = CatalogStore(tmp_path)
    (tmp_path / "snapshot-20260101T000000Z.partial").write_text("{ broken", encoding="utf-8")
    assert store.list_snapshot_ids() == []


def test_corrupt_snapshot_is_ignored(tmp_path: Path) -> None:
    (tmp_path / "snapshot-20260101T000000Z.json").write_text("not json", encoding="utf-8")
    assert CatalogStore(tmp_path).load("20260101T000000Z") is None


def test_snapshot_keeps_raw_payload(tmp_path: Path) -> None:
    """Raw data survives so old snapshots stay analysable when new fields appear."""
    store = CatalogStore(tmp_path)
    raw = [{"id": "a/one", "name": "one", "future_field": 42}]
    snapshot = store.save([make_model("a/one")], raw, source=MODELS_URL)
    stored = json.loads((tmp_path / f"snapshot-{snapshot.snapshot_id}.json").read_text("utf-8"))
    assert stored["models"][0]["future_field"] == 42


# ---------------------------------------------------------------------- client


@respx.mock
async def test_fetch_skips_broken_entries_without_failing() -> None:
    respx.get(MODELS_URL).mock(
        return_value=httpx.Response(
            200,
            json={"data": [{"id": "a/one", "name": "One"}, {"no": "id"}, "nonsense"]},
        )
    )
    models, raw = await fetch_models(url=MODELS_URL)
    assert [m.id for m in models] == ["a/one"]
    assert len(raw) == 3


@respx.mock
async def test_fetch_raises_on_http_error() -> None:
    respx.get(MODELS_URL).mock(return_value=httpx.Response(500))
    with pytest.raises(CatalogFetchError):
        await fetch_models(url=MODELS_URL)


@respx.mock
async def test_fetch_raises_when_nothing_parsable() -> None:
    respx.get(MODELS_URL).mock(return_value=httpx.Response(200, json={"data": [{"no": "id"}]}))
    with pytest.raises(CatalogFetchError):
        await fetch_models(url=MODELS_URL)


# --------------------------------------------------------------------- service


def _service(tmp_path: Path, fixture: list[OpenRouterModel] | None = None) -> CatalogService:
    fixture_path = tmp_path / "fixture.json"
    if fixture is not None:
        # mode="json": the store keeps OpenRouter's untouched JSON payload. A raw
        # model_dump() would contain Decimal objects and not be serialisable.
        CatalogStore(tmp_path / "fx").save(
            fixture, [m.model_dump(mode="json") for m in fixture], source="fixture"
        )
        built = next((tmp_path / "fx").glob("snapshot-*.json"))
        fixture_path.write_text(built.read_text("utf-8"), encoding="utf-8")
    return CatalogService(
        CatalogStore(tmp_path / "catalog"), fixture_path=fixture_path, source=MODELS_URL
    )


def test_fixture_is_used_when_never_synced(tmp_path: Path) -> None:
    state = _service(tmp_path, [make_model("a/one")]).current()
    assert state.is_fixture is True
    assert state.snapshot.model_count == 1


def test_snapshot_wins_over_fixture(tmp_path: Path) -> None:
    service = _service(tmp_path, [make_model("a/one")])
    CatalogStore(tmp_path / "catalog").save(
        [make_model("b/two"), make_model("c/three")],
        [{"id": "b/two", "name": "two"}, {"id": "c/three", "name": "three"}],
        source=MODELS_URL,
    )
    state = _service(tmp_path, [make_model("a/one")]).current()
    assert state.is_fixture is False
    assert state.snapshot.model_count == 2
    assert service is not None


def test_without_snapshot_and_fixture_it_says_so(tmp_path: Path) -> None:
    with pytest.raises(CatalogUnavailableError):
        _service(tmp_path).current()


# ------------------------------------------------------------------------- API


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    from hive.api.app import create_app
    from hive.api.deps import get_catalog_service

    service = _service(
        tmp_path,
        [
            make_model(
                "anthropic/claude-sonnet", prompt="0.000003", completion="0.000015", vision=True
            ),
            make_model("mistralai/small", prompt="0.0000002", completion="0.0000006"),
            make_model("meta/plain", tools=False),
        ],
    )

    # No monkeypatch on the module attribute: the routes hold a reference to the original
    # from import time, so dependency_overrides needs exactly that object as the key —
    # otherwise the override silently misses and the test would run against the real catalog.
    app = create_app()
    app.dependency_overrides[get_catalog_service] = lambda: service
    return TestClient(app)


def test_health(client: TestClient) -> None:
    assert client.get("/api/health").json()["status"] == "ok"


def test_status_reports_fixture_origin(client: TestClient) -> None:
    body = client.get("/api/catalog/status").json()
    assert body["is_fixture"] is True
    assert body["model_count"] == 3
    assert body["tool_capable_count"] == 2
    assert body["vision_capable_count"] == 1


def test_list_models_filters_and_paginates(client: TestClient) -> None:
    body = client.get("/api/catalog/models", params={"role": "inspector"}).json()
    assert body["total"] == 1
    assert body["items"][0]["id"] == "anthropic/claude-sonnet"

    page = client.get("/api/catalog/models", params={"limit": 2, "offset": 0}).json()
    assert page["total"] == 3
    assert len(page["items"]) == 2


def test_ineligible_reason_is_exposed_not_hidden(client: TestClient) -> None:
    """Models without tool calling do not disappear — they carry a reason."""
    body = client.get("/api/catalog/models", params={"search": "plain"}).json()
    assert body["items"][0]["ineligible_reason"] is not None
    assert body["items"][0]["roles"] == ["scout"]


def test_providers_facet(client: TestClient) -> None:
    providers = {p["provider"] for p in client.get("/api/catalog/providers").json()}
    assert providers == {"anthropic", "mistralai", "meta"}


def test_invalid_query_is_rejected(client: TestClient) -> None:
    assert client.get("/api/catalog/models", params={"limit": 9999}).status_code == 422
    assert client.get("/api/catalog/models", params={"role": "empress"}).status_code == 422
