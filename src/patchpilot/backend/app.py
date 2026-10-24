"""FastAPI application for PatchPilot.

Manages application lifespan, single background repair worker,
API routing, standardized error responses, and static/template serving.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from patchpilot.backend.api import (
    REGISTERED_SITES,
    _APPROVALS,
    FakeRepairService,
    get_api_router,
    worker_queue,
)
from patchpilot.backend.reconciliation import reconcile_interrupted_runs
from patchpilot.backend.storage import FileEventSink, FileRecipeStore, FileRunStore
from patchpilot.shared.settings import BASE_DIR, RECIPES_DIR, RUNS_DIR

logger = logging.getLogger("patchpilot.backend.app")

# Storage instances
run_store = FileRunStore(runs_dir=RUNS_DIR)
event_sink = FileEventSink(runs_dir=RUNS_DIR)
recipe_store = FileRecipeStore(recipes_dir=RECIPES_DIR)
repair_service = FakeRepairService(
    run_store=run_store,
    event_sink=event_sink,
    recipe_store=recipe_store,
    step_delay=0.05,
)


async def background_repair_worker(
    queue: asyncio.Queue[tuple[str, str, bool, str]], service: FakeRepairService
):
    """Lifespan-owned background worker consuming runs sequentially from worker_queue."""
    logger.info("Background repair worker started")
    try:
        while True:
            run_id, approval_id, memory_enabled, target_outcome = await queue.get()
            approval = _APPROVALS.get(approval_id)
            if not approval:
                logger.error("Approval %s not found for run %s", approval_id, run_id)
                queue.task_done()
                continue

            try:
                logger.info(
                    "Executing run %s for approval %s (target_outcome=%s)",
                    run_id,
                    approval_id,
                    target_outcome,
                )
                await service.run(
                    approval=approval,
                    memory_enabled=memory_enabled,
                    target_outcome=target_outcome,
                    run_id=run_id,
                )
            except Exception as e:
                logger.exception("Error executing run %s: %s", run_id, e)
            finally:
                queue.task_done()
    except asyncio.CancelledError:
        logger.info("Background repair worker cancelled on shutdown")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 1. Startup: Run reconciliation stub
    app_run_store = getattr(app.state, "run_store", run_store)
    app_repair_service = getattr(app.state, "repair_service", repair_service)

    await reconcile_interrupted_runs(run_store=app_run_store, repair_service=app_repair_service)

    # 2. Start single background worker with loop-scoped queue
    queue: asyncio.Queue[tuple[str, str, bool, str]] = asyncio.Queue()
    app.state.worker_queue = queue
    worker_task = asyncio.create_task(background_repair_worker(queue, app_repair_service))
    app.state.worker_task = worker_task

    yield

    # 3. Shutdown: Stop background worker
    worker_task.cancel()
    try:
        await worker_task
    except asyncio.CancelledError:
        pass


def create_app(
    custom_run_store: Optional[FileRunStore] = None,
    custom_event_sink: Optional[FileEventSink] = None,
    custom_recipe_store: Optional[FileRecipeStore] = None,
    custom_repair_service: Optional[FakeRepairService] = None,
) -> FastAPI:
    app = FastAPI(
        title="PatchPilot API",
        version="0.1.0",
        description="Autonomous, policy-bounded web application patching and repair platform",
        lifespan=lifespan,
    )

    actual_run_store = custom_run_store or run_store
    actual_event_sink = custom_event_sink or event_sink
    actual_recipe_store = custom_recipe_store or recipe_store
    actual_repair_service = custom_repair_service or repair_service

    app.state.run_store = actual_run_store
    app.state.event_sink = actual_event_sink
    app.state.recipe_store = actual_recipe_store
    app.state.repair_service = actual_repair_service

    # Attach router
    router = get_api_router(
        actual_run_store, actual_event_sink, actual_recipe_store, actual_repair_service
    )
    app.include_router(router)

    # Standard error handlers matching {error: {code, message, details}}
    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": {
                    "code": str(exc.status_code),
                    "message": exc.detail,
                    "details": {},
                }
            },
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": "Invalid request payload",
                    "details": exc.errors(),
                }
            },
        )

    @app.exception_handler(Exception)
    async def general_exception_handler(request: Request, exc: Exception):
        logger.exception("Unhandled server error: %s", exc)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "error": {
                    "code": "INTERNAL_SERVER_ERROR",
                    "message": str(exc),
                    "details": {},
                }
            },
        )

    # Web UI / static serving
    web_dir = BASE_DIR / "src" / "patchpilot" / "web"
    static_dir = web_dir / "static"
    templates_dir = web_dir / "templates"

    if static_dir.is_dir():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request):
        # Serve Teammate 4 templates if present
        dashboard_template = templates_dir / "dashboard.html"
        if dashboard_template.is_file():
            from jinja2 import Environment, FileSystemLoader

            jinja_env = Environment(loader=FileSystemLoader(str(templates_dir)))
            template = jinja_env.get_template("dashboard.html")
            context = {
                "csrf_token": "dev-csrf-token",
                "sites": list(REGISTERED_SITES.values()),
            }
            return HTMLResponse(template.render(context))

        # Default placeholder HTML page when Teammate 4 UI files are not yet created
        return HTMLResponse(
            """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>PatchPilot — Backend & Platform</title>
  <style>
    body { font-family: system-ui, -apple-system, sans-serif; max-width: 800px; margin: 40px auto; padding: 20px; line-height: 1.6; }
    h1 { color: #1e3a8a; }
    .badge { background: #dcfce7; color: #166534; padding: 4px 8px; border-radius: 4px; font-weight: bold; }
    .card { background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; padding: 16px; margin: 16px 0; }
    code { background: #f1f5f9; padding: 2px 6px; border-radius: 4px; font-size: 0.9em; }
    ul { list-style-type: square; }
  </style>
</head>
<body>
  <h1>PatchPilot Controller <span class="badge">Running</span></h1>
  <p>Backend & Platform engine active on Python 3.12, FastAPI, and asynchronous repair worker.</p>
  <div class="card">
    <h3>Registered Fleet Targets (team-plan §4)</h3>
    <ul>
      <li><code>pantry-a</code> (127.0.0.1:8081) — Homepage & Contact</li>
      <li><code>pantry-b</code> (127.0.0.1:8082) — Homepage & Contact</li>
      <li><code>clinic-a</code> (127.0.0.1:8083) — Homepage, Contact & 3 MiB Upload</li>
      <li><code>clinic-b</code> (127.0.0.1:8084) — Homepage, Contact & 3 MiB Upload</li>
    </ul>
  </div>
  <div class="card">
    <h3>API Endpoints</h3>
    <p>Explore interactive documentation at <a href="/docs"><code>/docs</code> (Swagger UI)</a> or <a href="/redoc"><code>/redoc</code></a>.</p>
  </div>
</body>
</html>"""
        )

    return app


app = create_app()
