"""Local real-service application with one lifespan-owned operation worker."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone
import inspect
import logging

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException

from patchpilot.backend.api import get_api_router
from patchpilot.backend.control import OperationControl, complete_before_cancel
from patchpilot.backend.reconciliation import TERMINAL_STATES, reconcile_interrupted_runs
from patchpilot.backend.storage import FileEventSink, FileRecipeStore, FileRunStore
from patchpilot.shared.contracts import RunRecord, RunState
from patchpilot.shared.ports import RepairService
from patchpilot.shared.settings import BASE_DIR, RECIPES_DIR, RUNS_DIR

logger = logging.getLogger(__name__)


async def _failed_run(app: FastAPI, run_id: str) -> RunRecord:
    store = app.state.run_store
    record = await store.get_run(run_id) or RunRecord(run_id=run_id)
    record.error = "Worker execution failed; deployment recovery is required"
    record.evidence_complete = False
    record.finished_at = datetime.now(timezone.utc).isoformat()
    await store.save_run(record)
    try:
        record = await app.state.repair_service.recover_interrupted(record)
        if record.state not in TERMINAL_STATES:
            raise RuntimeError("Recovery did not produce a terminal record")
    except Exception:
        record.state = RunState.RECOVERY_FAILED
        record.error = "Worker failure could not be reconciled; operator recovery is required"
        await store.save_run(record)
    return record


async def background_repair_worker(app: FastAPI) -> None:
    queue = app.state.worker_queue
    control: OperationControl = app.state.control
    service: RepairService = app.state.repair_service
    while True:
        item = await queue.get()
        if item is None:
            queue.task_done()
            return
        operation_id = item["id"]
        try:
            if item["kind"] == "run":
                try:
                    approval = await service.get_approval(item["approvalId"], item["session"])
                    record = await service.run(approval, memory_enabled=item["memoryEnabled"], run_id=operation_id, target_outcome=item["targetOutcome"])
                    if record.state not in TERMINAL_STATES:
                        raise RuntimeError("Service returned a nonterminal run")
                except Exception as exc:
                    logger.error("Repair worker failed (%s); attempting recorded recovery", type(exc).__name__)
                    record = await _failed_run(app, operation_id)
                if record.evidence_complete and record.state in TERMINAL_STATES and record.state != RunState.RECOVERY_FAILED:
                    await control.release(operation_id)
            else:
                control.resets[operation_id] = {"resetId": operation_id, "state": "RUNNING"}
                await control.persist()
                try:
                    result = await service.reset(clear_recipes=item["clearRecipes"])
                    if result.get("state") != "COMPLETED":
                        raise RuntimeError("Reset did not complete")
                    control.resets[operation_id] = {**result, "resetId": operation_id, "state": "COMPLETED"}
                    control.assessment_owners.clear()
                except Exception as exc:
                    logger.error("Fleet reset failed (%s)", type(exc).__name__)
                    control.resets[operation_id] = {"resetId": operation_id, "state": "FAILED", "message": "Fleet reset failed; preparation must be checked before a repair"}
                await control.persist()
                await control.release(operation_id)
        except Exception as exc:
            logger.error("Operation persistence failed (%s); reservation retained", type(exc).__name__)
        finally:
            queue.task_done()


@asynccontextmanager
async def lifespan(app: FastAPI):
    control: OperationControl = app.state.control
    await control.open()
    try:
        if app.state.repair_service is None:
            from patchpilot.core.service import RealRepairService
            app.state.repair_service = RealRepairService(app.state.run_store, app.state.event_sink, app.state.recipe_store)
        service = app.state.repair_service
        await reconcile_interrupted_runs(app.state.run_store, service)
        # Interrupted preparation/reset can be explicitly retried after process exit.
        if control.active and control.active["kind"] != "run":
            operation_id = control.active["id"]
            if operation_id in control.resets:
                control.resets[operation_id] = {"resetId": operation_id, "state": "FAILED", "message": "Controller stopped during reset; prepare the fleet again"}
            control.active = None
        unresolved = []
        cursor = None
        while True:
            records, cursor = await app.state.run_store.list_runs(limit=100, cursor=cursor)
            unresolved.extend(record for record in records if not record.evidence_complete or record.state not in TERMINAL_STATES or record.state == RunState.RECOVERY_FAILED)
            if cursor is None:
                break
        if unresolved:
            control.active = {"kind": "run", "id": unresolved[0].run_id}
        elif control.active:
            control.active = None
        await control.persist()
        app.state.worker_queue = asyncio.Queue()
        task = asyncio.create_task(background_repair_worker(app))
        app.state.worker_task = task
        try:
            yield
        finally:
            # Offloaded Docker/model work cannot be stopped by cancelling its await.
            # Drain the current bounded operation before closing its dependencies.
            await app.state.worker_queue.put(None)
            try:
                await complete_before_cancel(task)
            finally:
                result = service.close()
                if inspect.isawaitable(result):
                    await result
    finally:
        control.close()


def create_app(
    custom_run_store: FileRunStore | None = None,
    custom_event_sink: FileEventSink | None = None,
    custom_recipe_store: FileRecipeStore | None = None,
    custom_repair_service: RepairService | None = None,
) -> FastAPI:
    app = FastAPI(title="PatchPilot", version="0.1.0", lifespan=lifespan)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1", "[::1]", "testserver"])
    app.state.run_store = custom_run_store or FileRunStore(RUNS_DIR)
    app.state.event_sink = custom_event_sink or FileEventSink(app.state.run_store.runs_dir)
    app.state.recipe_store = custom_recipe_store or FileRecipeStore(RECIPES_DIR)
    app.state.repair_service = custom_repair_service
    app.state.control = OperationControl(app.state.run_store.runs_dir)
    app.include_router(get_api_router(app.state.run_store, app.state.event_sink, app.state.recipe_store))

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'"
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    def error(status_code: int, code: str, message: str, details: object = None) -> JSONResponse:
        return JSONResponse(status_code=status_code, content={"error": {"code": code, "message": message, "details": details or {}}})

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException):
        return error(exc.status_code, str(exc.status_code), str(exc.detail))

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        return error(422, "VALIDATION_ERROR", "Invalid request payload", jsonable_encoder(exc.errors()))

    @app.exception_handler(LookupError)
    async def lookup_error(request: Request, exc: LookupError):
        return error(404, "NOT_FOUND", str(exc))

    @app.exception_handler(ValueError)
    async def value_error(request: Request, exc: ValueError):
        return error(400, "INVALID_REQUEST", str(exc))

    @app.exception_handler(RuntimeError)
    async def unavailable_error(request: Request, exc: RuntimeError):
        return error(503, "UNAVAILABLE", "Operation unavailable; inspect readiness and local controller diagnostics")

    @app.exception_handler(Exception)
    async def internal_error(request: Request, exc: Exception):
        logger.error("Unhandled controller error (%s)", type(exc).__name__)
        return error(500, "INTERNAL_SERVER_ERROR", "Controller operation failed")

    static_dir = BASE_DIR / "src" / "patchpilot" / "static"

    @app.get("/", include_in_schema=False)
    async def index():
        return FileResponse(static_dir / "landing.html", headers={"Cache-Control": "no-store"})

    @app.get("/dashboard", include_in_schema=False)
    async def dashboard():
        return FileResponse(static_dir / "index.html", headers={"Cache-Control": "no-store"})

    @app.get("/dashboard/", include_in_schema=False)
    async def dashboard_canonical(request: Request):
        query = f"?{request.url.query}" if request.url.query else ""
        return RedirectResponse(f"/dashboard{query}", status_code=307)

    # Keep the explicit asset namespace and existing root asset URLs available.
    app.mount("/static", StaticFiles(directory=static_dir), name="static")
    app.mount("/", StaticFiles(directory=static_dir), name="dashboard-assets")
    return app


app = create_app()
