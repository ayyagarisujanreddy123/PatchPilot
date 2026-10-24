# PatchPilot dashboard

Plain HTML, CSS, and JavaScript ES modules, with no frontend build step. FastAPI serves `index.html` at `/` and this directory's assets. The dashboard assesses the configured PHP security policy on authorized, registered local fixtures. It does not scan or repair arbitrary remote websites.

## Layout

| File | Role |
| --- | --- |
| `index.html` | App shell, landmarks, module entry |
| `styles.css` | Theme, responsive layout, components |
| `js/main.js` | Routing, polling, approval orchestration, focus management |
| `js/api.js` | Resource API, CSRF session, approval/run submission, explicit mock selection |
| `js/live.js` | API field/state normalization and registered URL validation |
| `js/mock.js` | Explicit scripted playback (`?mock=1`) |
| `js/state.js` | Application store |
| `js/util.js` | DOM helpers using text insertion |
| `js/views/*.js` | Fleet, assessment/approval, run evidence, metrics, recipes, events, operator controls |

## Live local workflow

1. Open the dashboard served by FastAPI. The header identifies **Real local fixtures** or **Simulation** using `/api/health`; simulation never claims a real repair.
2. Use **Prepare local fixtures** when setup is required. Readiness messages report backend prerequisites. Preparation affects only registered project resources.
3. Enter one of the configured local base URLs, or select **Assess & review repair** on a fleet card. Other URLs receive an explanation that an authorized hosting connection is required. The supplied URL is never fetched by the frontend.
4. Review observed runtime, applicability, proposed changes, required checks, and exact scope. **Assess & review fleet repair** assesses each registered eligible site and requests one approval for that scope; the backend repairs it sequentially.
5. Approve the reviewed assessment fingerprints and policy revision. The frontend retains the returned approval ID and a stable run submission key across retries.
6. Open **View run** for actual checks, expected/observed evidence, security results, recovery, and provenance. Event polling retains an independent sequence cursor for each run. Historical reports remain reviewable after reset, with an explicit historical notice.

**Reset fleet** is an operator control with confirmation. It optionally clears recipe memory, waits for the reset operation, and retains completed run records. Real mode exposes no simulated fault toggle. Aggregate metrics and recipe browsing are labeled unavailable when the API does not expose them; the dashboard does not invent values.

## API contract

The dashboard consumes camelCase JSON and uppercase resource states through `js/api.js`, adapting values for presentation in `js/live.js`.

- `GET /api/health`, `GET /api/session`.
- `GET /api/sites`; `POST /api/assessments` with `{siteId}`.
- `POST /api/approvals` with `{assessments: [{assessmentId, fingerprint}], policyRevision}`.
- `POST /api/runs` with `{approvalId, memoryEnabled}` and an `Idempotency-Key`.
- Paginated `GET /api/runs`; `GET /api/runs/{runId}` and `/report`.
- `GET /api/runs/{runId}/events?after=<sequence>&limit=100`.
- `POST /api/prepare`; `POST /api/resets` with `{clearRecipes}` and `GET /api/resets/{resetId}`.

Mutation requests use the backend session cookie and `X-CSRF-Token`; browser same-origin headers accompany requests. Lists use `{items, nextCursor}`; events use `{items, nextSequence}`. Errors use `{error: {code, message, details}}`. The frontend verifies that returned approval scope matches the reviewed site IDs before submitting any run.

## Scripted mock preview

From this directory:

```bash
python3 -m http.server 8765
```

Open `http://127.0.0.1:8765/?mock=1`. This standalone preview requires no backend. The header and evidence views identify simulated data. Switching to **Use demo data** after an API failure is explicit.

The mock fleet uses `site-a`/`site-b`/`site-c`/`site-d`; live mode uses the backend's registered IDs and capabilities. Mock-only controls provide a seeded upload-limit rejection. `?mock=1&scenario=rollback` and `?mock=1&scenario=restorefail` demonstrate simulated recovery outcomes. These scenarios are not evidence of actual runtime operations.

## Verification

From the repository root:

```bash
node src/patchpilot/static/scripts/verify-api.mjs
node src/patchpilot/static/scripts/verify-mock.mjs
```

The API script uses a fetch test double and makes no network requests. It checks resource paths, CSRF, exact approval scope, retry idempotency, pagination, per-site fleet outcomes, reset freshness, event cursors, URL authorization boundaries, and simulation identification. The mock script checks the timed fleet/reuse/rejection, reset, queue, restoration, and restoration-failure stories. Browser verification is additionally required for responsive layout, keyboard focus, and real API integration.
