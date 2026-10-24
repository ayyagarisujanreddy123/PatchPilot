# PatchPilot

PatchPilot repairs a registered local Apache/PHP demonstration fleet through assessment, owner approval, isolated staging, unchanged functional checks, activation, and live verification. The default server uses `RealRepairService`, the Docker runtime, and the Anthropic planner. Test simulations require explicit dependency injection and identify their evidence as `SIMULATION` / `TEST_DOUBLE`.

The implementation separates `core/` assessment, policy, planning, and repair control; `runtime/` Docker lifecycle and HTTP verification; `backend/` API admission, sessions, persistence, and restart recovery; `shared/` camelCase API contracts; and `static/` the dashboard. Python code lives under `src/patchpilot/`, tests under `tests/`, and local application fixtures under `fixtures/`.

## Install and start

Python 3.12 or newer and [uv](https://docs.astral.sh/uv/) are required. From the repository root:

```bash
uv sync --locked --extra dev
```

Configure `ANTHROPIC_API_KEY` and optionally `ANTHROPIC_MODEL` in the local, ignored `.env` or environment. The planner rejects the placeholder key and sends requests only to Anthropic's fixed API destination. Keep the key outside Git and dashboard requests.

Start the existing local demo Docker context, then start one controller process:

```bash
DOCKER_CONTEXT=lima-patchpilot-demo uv run --locked --extra dev uvicorn patchpilot.backend.app:app --host 127.0.0.1 --port 8765 --workers 1
```

This selects a context for that process; it does not change the user's default Docker context. If the authorized project context has another name, supply that name explicitly. Open `http://127.0.0.1:8765/` and use **Prepare fleet** to resolve the approved image digest, build the project fixtures, and establish the local targets. The registered fleet uses loopback ports 8081–8084. Readiness and preparation failures are reported by `/api/health` and the dashboard.

Assess the selected sites, review their actual runtime findings, approve the exact assessment fingerprints, and start a repair. Each run records its plan source and provider provenance, verification checks, current checkpoint, per-site outcomes, and final evidence status. A restored original remains unpatched. Incomplete evidence or failed recovery retains the operation reservation until recovery succeeds. Reset returns the project fleet to its baseline and optionally clears verified recipe memory while retaining completed run history.

`var/runs/<runId>/run.json` holds durable snapshots and complete recovery checkpoints; `events.ndjson` is the ordered append-only UI journal. Recipes live under `var/recipes/`. Controller operation metadata is stored under `var/.patchpilot-control/`. Atomic snapshot replacement syncs the containing directory, and journal appends are flushed and synced. A process lock prevents two controllers from operating on the same data directory.

## API workflow

`GET /api/session` issues an HttpOnly, SameSite=Strict operator cookie and returns `{csrfToken}`. Every mutation requires `X-CSRF-Token` and a matching `Origin` or `Referer`. Sessions last eight hours and are invalidated on controller restart; obtain fresh assessments and approval after restarting.

The dashboard uses these routes:

- `GET /api/health`, `GET /api/sites`, and `POST /api/prepare`.
- `POST /api/assessments` with `{siteId}`, or `POST /api/sites/{siteId}/assessments`.
- `POST /api/approvals` with `{assessments: [{assessmentId, fingerprint}], policyRevision}`. Assessment selection and approval are bound to the issuing session.
- `POST /api/runs` with `{approvalId, memoryEnabled}` and a required `Idempotency-Key`. Exact retries return the original run; a changed payload with the same key returns 409. Caller-supplied approvals are never synthesized. `targetOutcome` is accepted only by an explicitly injected simulation service.
- `GET /api/runs`, `GET /api/runs/{runId}`, `GET /api/runs/{runId}/events?after=0`, and `GET /api/runs/{runId}/report`.
- `POST /api/resets` with `{clearRecipes}` returns 202 and a status URL. Poll `GET /api/resets/{resetId}` until `COMPLETED` or `FAILED`.

Run, reset, preparation, and assessment admission share one reservation. Conflicting operations return 409. Shutdown drains the current bounded operation before closing dependencies. Unexpected worker failures invoke recorded recovery and produce a terminal failure record if recovery cannot be verified. Reports contain recorded results; missing evidence never becomes an invented security success.

## Verify

Run deterministic core, backend, and runtime-boundary tests without Docker or provider requests:

```bash
uv run --locked --extra dev python -m pytest -p no:cacheprovider -m 'not docker and not live_model'
```

Run backend tests alone:

```bash
uv run --locked --extra dev python -m pytest -p no:cacheprovider tests/backend
```

Docker fixture/verification tests exercise real local containers and HTTP requests:

```bash
DOCKER_CONTEXT=lima-patchpilot-demo uv run --locked --extra dev python -m pytest -p no:cacheprovider -m docker tests/runtime
```

The runtime suite includes the actual 3 MiB upload byte-count/hash contract, isolated staging, activation, restoration, and project-scoped reset. These tests modify only their registered project/test resources. The separate opt-in provider/whole-demo check is documented in `src/patchpilot/core/README.md`; provider access alone does not establish a verified deployment.

`pyproject.toml` and `uv.lock` define reproducible dependencies. Backend tests cover session ownership, CSRF/origin validation, exact site binding, idempotency, exclusive admission, durable storage, recovery, shutdown, and visibly simulated workflow outcomes. Simulated test passes are recorded separately from Docker and live-provider acceptance. Source review and whitespace checks use `git diff --check`; no repository-wide formatter or linter policy is currently enforced.
