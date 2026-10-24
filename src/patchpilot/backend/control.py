"""Local operator sessions and a single durable operation reservation."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from collections.abc import Awaitable
import fcntl
import hashlib
import json
from pathlib import Path
import secrets
import time
from typing import Any, AsyncIterator
from urllib.parse import urlsplit

from fastapi import HTTPException, Request

from patchpilot.backend.storage import _atomic_write_text

SESSION_COOKIE = "patchpilot_session"
SESSION_MAX_AGE = 8 * 60 * 60


async def complete_before_cancel(operation: Awaitable[Any]) -> Any:
    """Cancellation must not release admission while an offloaded operation runs."""
    task = asyncio.ensure_future(operation)
    cancelled = False
    while True:
        try:
            result = await asyncio.shield(task)
            break
        except asyncio.CancelledError:
            if task.cancelled():
                raise
            cancelled = True
    if cancelled:
        raise asyncio.CancelledError
    return result


class OperationControl:
    """One controller process per data directory; one modifying operation at a time."""

    def __init__(self, runs_dir: Path):
        self.directory = runs_dir.parent / ".patchpilot-control"
        self.lock = asyncio.Lock()
        self.active: dict[str, str] | None = None
        self.sessions: dict[str, str] = {}
        self.session_expiry: dict[str, float] = {}
        self.assessment_owners: dict[str, str] = {}
        self.idempotency: dict[str, dict[str, Any]] = {}
        self.resets: dict[str, dict[str, Any]] = {}
        self._process_lock: Any = None

    async def open(self) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        handle = (self.directory / "controller.lock").open("a+")
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            handle.close()
            raise RuntimeError("Another PatchPilot controller owns this data directory") from None
        self._process_lock = handle
        path = self.directory / "operations.json"
        if path.exists():
            try:
                stored = json.loads(path.read_text(encoding="utf-8"))
                self.idempotency = stored["idempotency"]
                self.resets = stored["resets"]
                self.active = stored.get("active")
            except (ValueError, KeyError, TypeError):
                self.close()
                raise RuntimeError("Operation history is unreadable; recovery is required") from None

    def close(self) -> None:
        if self._process_lock is not None:
            fcntl.flock(self._process_lock.fileno(), fcntl.LOCK_UN)
            self._process_lock.close()
            self._process_lock = None

    async def persist(self) -> None:
        payload = json.dumps({"active": self.active, "idempotency": self.idempotency, "resets": self.resets})
        await asyncio.to_thread(_atomic_write_text, self.directory / "operations.json", payload)

    async def reserve(self, kind: str, operation_id: str) -> None:
        # Callers holding lock use reserve_unlocked for atomic replay/reservation.
        async with self.lock:
            await self.reserve_unlocked(kind, operation_id)

    async def reserve_unlocked(self, kind: str, operation_id: str) -> None:
        if self.active:
            raise HTTPException(409, "Another operation is active or needs recovery")
        self.active = {"kind": kind, "id": operation_id}
        try:
            await self.persist()
        except Exception:
            self.active = None
            raise

    async def release(self, operation_id: str) -> None:
        async with self.lock:
            if self.active and self.active["id"] == operation_id:
                previous = self.active
                self.active = None
                try:
                    await self.persist()
                except Exception:
                    self.active = previous
                    raise

    @asynccontextmanager
    async def operation(self, kind: str, operation_id: str) -> AsyncIterator[None]:
        await self.reserve(kind, operation_id)
        try:
            yield
        finally:
            await self.release(operation_id)

    @staticmethod
    def replay_key(session_id: str, key: str) -> str:
        return hashlib.sha256(f"{session_id}\0{key}".encode()).hexdigest()


def operator_session(request: Request) -> str:
    control: OperationControl = request.app.state.control
    session_id = request.cookies.get(SESSION_COOKIE, "")
    if session_id not in control.sessions or control.session_expiry.get(session_id, 0) <= time.time():
        control.sessions.pop(session_id, None)
        control.session_expiry.pop(session_id, None)
        raise HTTPException(403, "Establish a local operator session first")
    return session_id


def _origin(value: str) -> tuple[str, str, int] | None:
    try:
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
            return None
        return parsed.scheme, parsed.hostname.lower(), parsed.port or (443 if parsed.scheme == "https" else 80)
    except ValueError:
        return None


def require_mutation(request: Request) -> str:
    session_id = operator_session(request)
    control: OperationControl = request.app.state.control
    token = request.headers.get("X-CSRF-Token", "")
    if not token or not secrets.compare_digest(token, control.sessions[session_id]):
        raise HTTPException(403, "A valid CSRF token is required")
    source = request.headers.get("Origin") or request.headers.get("Referer", "")
    if request.headers.get("Sec-Fetch-Site") == "cross-site" or not source or _origin(source) != _origin(str(request.base_url)):
        raise HTTPException(403, "Mutations require the same origin as this controller")
    return session_id
