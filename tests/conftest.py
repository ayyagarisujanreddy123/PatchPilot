"""Shared test fixtures for PatchPilot backend test suite."""

import asyncio
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from patchpilot.backend.api import (
    FakeRepairService,
    get_api_router,
    worker_queue,
)
from patchpilot.backend.storage import FileEventSink, FileRecipeStore, FileRunStore
from patchpilot.shared.contracts import (
    Approval,
    AssessmentApprovalItem,
    CheckResult,
    RunRecord,
    RunState,
)


@pytest.fixture
def temp_storage(tmp_path: Path):
    """Temporary storage paths for isolated unit tests."""
    runs_dir = tmp_path / "runs"
    recipes_dir = tmp_path / "recipes"
    runs_dir.mkdir(parents=True, exist_ok=True)
    recipes_dir.mkdir(parents=True, exist_ok=True)
    return runs_dir, recipes_dir


@pytest.fixture
def run_store(temp_storage):
    runs_dir, _ = temp_storage
    return FileRunStore(runs_dir=runs_dir)


@pytest.fixture
def event_sink(temp_storage):
    runs_dir, _ = temp_storage
    return FileEventSink(runs_dir=runs_dir)


@pytest.fixture
def recipe_store(temp_storage):
    _, recipes_dir = temp_storage
    return FileRecipeStore(recipes_dir=recipes_dir)


@pytest.fixture
def fast_repair_service(run_store, event_sink, recipe_store):
    """FakeRepairService with step_delay=0 for instant unit test execution."""
    return FakeRepairService(
        run_store=run_store,
        event_sink=event_sink,
        recipe_store=recipe_store,
        step_delay=0.001,
    )
