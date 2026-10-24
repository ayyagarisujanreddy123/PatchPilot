"""Isolated backend storage and explicitly simulated service fixtures."""

import pytest

from patchpilot.backend.api import FakeRepairService
from patchpilot.backend.storage import FileEventSink, FileRecipeStore, FileRunStore


@pytest.fixture
def temp_storage(tmp_path):
    return tmp_path / "runs", tmp_path / "recipes"


@pytest.fixture
def run_store(temp_storage):
    return FileRunStore(temp_storage[0])


@pytest.fixture
def event_sink(temp_storage):
    return FileEventSink(temp_storage[0])


@pytest.fixture
def recipe_store(temp_storage):
    return FileRecipeStore(temp_storage[1])


@pytest.fixture
def fast_repair_service(run_store, event_sink, recipe_store):
    return FakeRepairService(run_store, event_sink, recipe_store, step_delay=0.001)


@pytest.fixture
def client(fast_repair_service, run_store, event_sink, recipe_store):
    from fastapi.testclient import TestClient
    from patchpilot.backend.app import create_app

    with TestClient(create_app(run_store, event_sink, recipe_store, fast_repair_service)) as client:
        csrf = client.get("/api/session").json()["csrfToken"]
        client.headers.update({"X-CSRF-Token": csrf, "Origin": "http://testserver"})
        yield client
