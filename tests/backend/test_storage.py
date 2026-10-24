"""Unit tests for storage persistence and atomic journals."""

import pytest
from patchpilot.backend.storage import FileEventSink, FileRecipeStore, FileRunStore
from patchpilot.shared.contracts import (
    CheckResult,
    PlanSource,
    Recipe,
    RepairPlan,
    RunEvent,
    RunRecord,
    RunState,
)


@pytest.mark.asyncio
async def test_run_store_atomic_write_and_read(run_store: FileRunStore):
    run = RunRecord(
        run_id="run-atomic-1",
        site_ids=["pantry-a"],
        current_site_id="pantry-a",
        state=RunState.VERIFYING,
        attempt=1,
        plan_source=PlanSource.TEST_DOUBLE,
        checks=[
            CheckResult(
                check_id="homepage",
                site_id="pantry-a",
                phase="STAGING",
                passed=True,
                message="OK",
                duration_ms=10,
            )
        ],
        warnings=["warning-1"],
    )

    await run_store.save_run(run)

    loaded = await run_store.get_run("run-atomic-1")
    assert loaded is not None
    assert loaded.run_id == "run-atomic-1"
    assert loaded.schema_version == 1
    assert loaded.state == RunState.VERIFYING
    assert loaded.checks[0].check_id == "homepage"
    assert loaded.warnings == ["warning-1"]

    missing = await run_store.get_run("non-existent-run")
    assert missing is None


@pytest.mark.asyncio
async def test_run_store_listing_and_pagination(run_store: FileRunStore):
    for i in range(1, 6):
        r = RunRecord(run_id=f"run-list-{i}", state=RunState.VERIFIED)
        await run_store.save_run(r)

    runs, next_cursor = await run_store.list_runs(limit=3)
    assert len(runs) == 3
    assert next_cursor is not None

    remaining, next_cursor2 = await run_store.list_runs(limit=3, cursor=next_cursor)
    assert len(remaining) == 2
    assert next_cursor2 is None


@pytest.mark.asyncio
async def test_event_sink_ordering_and_cursor(event_sink: FileEventSink):
    run_id = "run-events-1"
    for seq in range(1, 7):
        ev = RunEvent(
            sequence=seq,
            timestamp=f"2026-10-24T12:00:0{seq}Z",
            site_id="pantry-a",
            state=RunState.VERIFYING if seq < 6 else RunState.VERIFIED,
            message=f"Step {seq}",
        )
        await event_sink.append_event(run_id, ev)

    # Full query
    all_events, next_seq = await event_sink.get_events(run_id, after_sequence=0)
    assert len(all_events) == 6
    assert [e.sequence for e in all_events] == list(range(1, 7))
    assert next_seq == 6

    # Cursor query
    paged, next_seq2 = await event_sink.get_events(run_id, after_sequence=3)
    assert len(paged) == 3
    assert [e.sequence for e in paged] == [4, 5, 6]
    assert next_seq2 == 6

    # Non-existent run
    empty, zero_seq = await event_sink.get_events("non-existent")
    assert empty == []
    assert zero_seq == 0


@pytest.mark.asyncio
async def test_recipe_store_matching_and_clear(recipe_store: FileRecipeStore):
    recipe = Recipe(
        recipe_id="rec-compat-1",
        compatibility_key="compat-hash-999",
        successful_plan=RepairPlan(
            target_image_alias="php:8.3.36-apache",
            configuration_profile_id="default",
            rationale="Passes checks",
        ),
        originating_run_id="run-orig-1",
        originating_site_id="pantry-a",
        verified_at="2026-10-24T12:00:00Z",
    )
    await recipe_store.save_recipe(recipe)

    found = await recipe_store.find_matching("compat-hash-999")
    assert found is not None
    assert found.recipe_id == "rec-compat-1"

    missing = await recipe_store.find_matching("different-hash")
    assert missing is None

    cleared = await recipe_store.clear_recipes()
    assert cleared == 1
    assert await recipe_store.get_recipe("rec-compat-1") is None
