"""Atomic filesystem storage for RunRecords, Recipes, and Event journals.

Implements RunStore, RecipeStore, and EventSink protocols.
"""

from __future__ import annotations

import asyncio
import os
import re
from pathlib import Path
from typing import Optional
import uuid

from patchpilot.shared.contracts import Recipe, RunEvent, RunRecord
from patchpilot.shared.ports import EventSink, RecipeStore, RunStore
from patchpilot.shared.settings import RECIPES_DIR, RUNS_DIR


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _safe_identifier(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", value):
        raise ValueError("Invalid storage identifier")
    return value


def _ensure_directory(path: Path) -> None:
    missing = []
    current = path
    while not current.exists():
        missing.append(current)
        current = current.parent
    for directory in reversed(missing):
        directory.mkdir(exist_ok=True)
        _fsync_directory(directory.parent)


def _atomic_write_text(path: Path, content: str) -> None:
    """Atomically write text content using a temporary file and os.replace in the same directory."""
    _ensure_directory(path.parent)
    tmp_path = path.parent / f".{path.name}.tmp.{uuid.uuid4().hex}"
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
        _fsync_directory(path.parent)
    except Exception:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass
        raise


class FileRunStore(RunStore):
    """Persists RunRecord snapshots as var/runs/<runId>/run.json with atomic writes."""

    def __init__(self, runs_dir: Path | str = RUNS_DIR):
        self.runs_dir = Path(runs_dir)

    def _run_path(self, run_id: str) -> Path:
        return self.runs_dir / _safe_identifier(run_id) / "run.json"

    async def get_run(self, run_id: str) -> Optional[RunRecord]:
        path = self._run_path(run_id)
        if not path.is_file():
            return None
        content = await asyncio.to_thread(path.read_text, encoding="utf-8")
        try:
            return RunRecord.model_validate_json(content)
        except ValueError:
            raise RuntimeError("A run snapshot is unreadable; recovery is required") from None

    async def save_run(self, record: RunRecord) -> None:
        path = self._run_path(record.run_id)
        payload = record.model_dump_json(by_alias=True, indent=2)
        await asyncio.to_thread(_atomic_write_text, path, payload)

    async def list_runs(
        self, limit: int = 50, cursor: Optional[str] = None
    ) -> tuple[list[RunRecord], Optional[str]]:
        if not self.runs_dir.is_dir():
            return [], None

        run_dirs = [d for d in self.runs_dir.iterdir() if d.is_dir() and not d.name.startswith(".")]
        # Sort by mtime descending (most recent first) or directory name
        run_dirs.sort(
            key=lambda d: (d / "run.json").stat().st_mtime if (d / "run.json").exists() else 0,
            reverse=True,
        )

        runs: list[RunRecord] = []
        start_idx = 0
        if cursor:
            for idx, d in enumerate(run_dirs):
                if d.name == cursor:
                    start_idx = idx + 1
                    break

        paged_dirs = run_dirs[start_idx : start_idx + limit]
        for d in paged_dirs:
            run_file = d / "run.json"
            if run_file.is_file():
                try:
                    content = await asyncio.to_thread(run_file.read_text, encoding="utf-8")
                    runs.append(RunRecord.model_validate_json(content))
                except (ValueError, OSError):
                    raise RuntimeError("A run snapshot is unreadable; recovery is required") from None

        next_cursor = None
        if start_idx + limit < len(run_dirs):
            next_cursor = run_dirs[start_idx + limit - 1].name

        return runs, next_cursor


class FileRecipeStore(RecipeStore):
    """Persists validated Recipes under var/recipes/<recipeId>.json with atomic writes."""

    def __init__(self, recipes_dir: Path | str = RECIPES_DIR):
        self.recipes_dir = Path(recipes_dir)

    def _recipe_path(self, recipe_id: str) -> Path:
        return self.recipes_dir / f"{_safe_identifier(recipe_id)}.json"

    async def get_recipe(self, recipe_id: str) -> Optional[Recipe]:
        path = self._recipe_path(recipe_id)
        if not path.is_file():
            return None
        content = await asyncio.to_thread(path.read_text, encoding="utf-8")
        return Recipe.model_validate_json(content)

    async def find_matching(self, compatibility_key: str) -> Optional[Recipe]:
        if not self.recipes_dir.is_dir():
            return None

        for path in self.recipes_dir.glob("*.json"):
            if path.name.startswith("."):
                continue
            try:
                content = await asyncio.to_thread(path.read_text, encoding="utf-8")
                recipe = Recipe.model_validate_json(content)
                if recipe.compatibility_key == compatibility_key:
                    return recipe
            except Exception:
                continue
        return None

    async def save_recipe(self, recipe: Recipe) -> None:
        path = self._recipe_path(recipe.recipe_id)
        payload = recipe.model_dump_json(by_alias=True, indent=2)
        await asyncio.to_thread(_atomic_write_text, path, payload)

    async def clear_recipes(self) -> int:
        if not self.recipes_dir.is_dir():
            return 0

        count = 0
        for path in self.recipes_dir.glob("*.json"):
            if not path.name.startswith("."):
                try:
                    path.unlink()
                    count += 1
                except OSError:
                    pass
        return count


class FileEventSink(EventSink):
    """Appends ordered run events into var/runs/<runId>/events.ndjson."""

    def __init__(self, runs_dir: Path | str = RUNS_DIR):
        self.runs_dir = Path(runs_dir)
        self._locks: dict[str, asyncio.Lock] = {}
        self._global_lock = asyncio.Lock()

    def _events_path(self, run_id: str) -> Path:
        return self.runs_dir / _safe_identifier(run_id) / "events.ndjson"

    async def _get_lock(self, run_id: str) -> asyncio.Lock:
        async with self._global_lock:
            if run_id not in self._locks:
                self._locks[run_id] = asyncio.Lock()
            return self._locks[run_id]

    async def append_event(self, run_id: str, event: RunEvent) -> None:
        lock = await self._get_lock(run_id)
        path = self._events_path(run_id)

        async with lock:
            _ensure_directory(path.parent)
            line = event.model_dump_json(by_alias=True) + "\n"

            def _append():
                maximum = 0
                if path.exists():
                    for existing_line in path.read_text(encoding="utf-8").splitlines():
                        if existing_line.strip():
                            try:
                                previous = RunEvent.model_validate_json(existing_line)
                            except ValueError:
                                raise RuntimeError("Run journal is unreadable; recovery is required") from None
                            if previous.sequence != maximum + 1:
                                raise RuntimeError("Run journal sequence is invalid")
                            maximum = previous.sequence
                if event.sequence != maximum + 1:
                    raise ValueError("Run events must have consecutive unique sequence numbers")
                with open(path, "a", encoding="utf-8") as f:
                    f.write(line)
                    f.flush()
                    os.fsync(f.fileno())
                _fsync_directory(path.parent)

            await asyncio.to_thread(_append)

    async def get_events(
        self, run_id: str, after_sequence: int = 0, limit: int = 100
    ) -> tuple[list[RunEvent], int]:
        path = self._events_path(run_id)
        if not path.is_file():
            return [], 0

        lock = await self._get_lock(run_id)

        def _read_events():
            events: list[RunEvent] = []
            max_seq = 0
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        ev = RunEvent.model_validate_json(line)
                        if ev.sequence != max_seq + 1:
                            raise RuntimeError("Run journal sequence is invalid")
                        max_seq = ev.sequence
                        if ev.sequence > after_sequence:
                            events.append(ev)
                    except ValueError:
                        raise RuntimeError("Run journal is unreadable; recovery is required") from None
            paged = events[:limit]
            next_seq = paged[-1].sequence if paged else max_seq
            return paged, next_seq

        async with lock:
            return await asyncio.to_thread(_read_events)
