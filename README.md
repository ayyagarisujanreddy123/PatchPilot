# PatchPilot

Autonomous, policy-bounded web application patching and repair platform.

## Architecture & Workstreams
- `src/patchpilot/core/`: Security assessment, AI planner, policy enforcement, recovery decisions, verified recipe memory (Lead: Sujan).
- `src/patchpilot/runtime/`: Docker fixtures, deployment adapter, real HTTP checks, restoration, and reset (Lead: Nicholas).
- `src/patchpilot/shared/`: Shared contracts, protocols/ports, settings (Lead: Aykhan).
- `src/patchpilot/backend/`: FastAPI application, API routes, atomic JSON storage, repair worker, reconciliation (Lead: Aykhan).
- `src/patchpilot/web/`: Templates, static assets, dashboard UI (Lead: Teammate 4).

## Setup & Development
```bash
# Using uv (recommended)
uv venv --python 3.12
source .venv/bin/activate
uv pip install -e ".[dev]"

# Run tests
pytest tests/backend
```
