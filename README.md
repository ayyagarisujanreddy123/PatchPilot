# PatchPilot

PatchPilot's default dashboard assesses a real public website URL, collects fresh HTTP response evidence, and obtains Anthropic remediation guidance tied to those observations. It shows collection and agent activity, PHP detection confidence, evidence-linked findings, suggested configuration/code, and the assessment's coverage and limitations. The separate **Repair lab** retains the approved local Apache/PHP deployment-repair workflow.

The implementation separates `webscan/` public HTTP collection, rules, and Anthropic analysis; `core/` local repair assessment, policy, planning, and control; `runtime/` Docker lifecycle and HTTP verification; `backend/` sessions, job admission, persistence, and recovery; `shared/` camelCase contracts; and `static/` the landing page and dashboard. Python code lives under `src/patchpilot/`, tests under `tests/`, and local repair fixtures under `fixtures/`.

## Install and launch

Python 3.12 or newer and [uv](https://docs.astral.sh/uv/) are required. From the repository root:

```bash
uv sync --locked --extra dev
```

Configure `ANTHROPIC_API_KEY` and optionally `ANTHROPIC_MODEL` in the local, ignored `.env` or environment. Keep credentials outside Git, URLs, and dashboard inputs. The Anthropic client uses the fixed provider API destination; missing or failed provider access produces an explicit assessment failure while retaining collected observations.

Start one application process:

```bash
uv run --locked --extra dev uvicorn patchpilot.backend.app:app --host 127.0.0.1 --port 8765 --workers 1
```

Open **[http://127.0.0.1:8765/dashboard](http://127.0.0.1:8765/dashboard)**. This is the single dashboard URL; **Website assessment** is the default task. Public website assessment requires no Docker preparation or repair approval. The product landing page remains at `/`.

## Assess a real website

1. Select **Invicti PHP test site** to fill `http://php.testsparker.com/`, or enter a public HTTP(S) page URL. The sample button fills the form only; it does not load precomputed results or start a request.
2. Select **Assess website**. The backend collects fresh, bounded normal GET responses and records their status, elapsed time, byte count, body SHA-256, and observations.
3. Watch **Live agent activity**. `COLLECTING` describes actual HTTP collection; `ANALYZING` identifies the Anthropic agent. Generation messages report characters received from the actual provider stream, with recorded event timestamps. The UI uses no fabricated completion percentage or timed result playback.
4. Review PHP detection as `REPORTED`, `INFERRED`, or `UNKNOWN`, then follow each finding's evidence links. A public PHP banner does not prove the installed binary's patch or backport status.
5. Review the validated Anthropic guidance: explanation, suggested steps/configuration/code, verification, and access requirements. **Analysis provenance** shows the returned model ID, provider message ID, and input/output token usage. Code appears only after the structured response is validated.

**Assessment completed** means collection and analysis completed. Website assessment does not apply a patch or declare a website safe. Suggested changes require owner review and authorized configuration/source access. Public-response findings do not establish source-level vulnerabilities or comprehensive penetration-test coverage.

Only public HTTP(S) destinations on ports 80/443 are accepted; credentials, query parameters, private/reserved addresses, and unsafe redirect destinations are rejected. Collection uses normal GETs rather than exploit payloads, form submissions, credential use, or server changes. The model receives normalized observations rather than full HTML, cookie values, or credentials.

Collection/provider failures remain `FAILED`, with any partial observations and a clear error. No fixture observation, cached example, or simulated AI result replaces failed live work. Use **Assess this URL again** for a fresh assessment. Reports belong to the browser's operator session; restarting the controller invalidates that session.

See the [demo guide](docs/demo/demo-script.md) for the one-site walkthrough. The guide records a completed 2026-10-24 browser/Anthropic assessment of the public sample, with its actual response fingerprint and provider metadata, separately from test-double checks.

## Separate repair lab

Select **Repair lab**, or visit `/dashboard#/fleet`, to use the four registered local fixtures. This workflow uses `RealRepairService`, the Docker runtime, and the Anthropic planner. It remains separate from public website assessment and can change only registered project deployments within explicit approval.

For the lab, start the existing authorized Docker context and run the same single application process with that context selected:

```bash
DOCKER_CONTEXT=lima-patchpilot-demo uv run --locked --extra dev uvicorn patchpilot.backend.app:app --host 127.0.0.1 --port 8765 --workers 1
```

Stop an existing application process before changing its context. The variable selects a context for that process; it does not change the user's default context. Supply the actual authorized context name if it differs.

Use **Prepare demo sites** to resolve the approved image digest, build the fixtures, and check ports 8081–8084. Assess selected sites, review their runtime findings, approve the exact assessment fingerprints, and start the repair. Candidate and live checks use the same contract, including real 3 MiB upload size/hash checks on upload fixtures. A restored original remains unpatched. Reset restores the project baseline, optionally clears recipes, and retains completed run records.

The explicit lab simulation is `/dashboard?mock=1#/fleet`; its scripted evidence is labeled simulated. It is a repair-lab walkthrough, never a fallback for real website assessment.

## API and records

`GET /api/session` establishes an HttpOnly, SameSite=Strict operator cookie and returns `{csrfToken}`. Website reads require that session; every mutation also requires `X-CSRF-Token` and matching `Origin` or `Referer`. Sessions last eight hours and are invalidated on controller restart.

The default website flow uses:

- `GET /api/website-assessments/examples`: public sample metadata only.
- `POST /api/website-assessments` with `{url}`: returns 202 `{assessmentId, statusUrl}`.
- `GET /api/website-assessments/{assessmentId}`: current typed report, actual activity, partial observations, and final analysis/error.
- `GET /api/website-assessments`: the issuing session's assessment records.

Reports progress through `QUEUED`, `COLLECTING`, `ANALYZING`, and `COMPLETED` or `FAILED`. Records are persisted under `var/website-assessments/`. Website jobs share exclusive operation admission with the repair lab; conflicts return 409, and assessment start limits return 429. The [website specification](docs/specs/live-website-assessment.md) defines the contract and boundaries.

The repair lab retains `/api/health`, `/api/sites`, `/api/prepare`, `/api/assessments`, `/api/approvals`, `/api/runs`, run events/reports, and `/api/resets`. Approval is bound to the issuing session and exact assessments. Run submission requires an `Idempotency-Key`; an exact retry returns the existing run, while a changed payload with that key returns 409. Caller-supplied approvals are never synthesized.

Repair snapshots/checkpoints live at `var/runs/<runId>/run.json`, ordered append-only events at `events.ndjson`, recipes under `var/recipes/`, and operation metadata under `var/.patchpilot-control/`. A process lock prevents two controllers using the same data directory. Recovery failure retains the reservation until resolved. Reports expose recorded evidence rather than invented success values.

## Verify

Run deterministic tests without Docker or live provider requests:

```bash
uv run --locked --extra dev python -m pytest -p no:cacheprovider -m 'not docker and not live_model'
```

Focused website/backend and frontend contract checks:

```bash
uv run --locked --extra dev python -m pytest -p no:cacheprovider tests/webscan tests/backend
node src/patchpilot/static/scripts/verify-website.mjs
node src/patchpilot/static/scripts/verify-api.mjs
```

The website frontend script uses a fetch test double and makes no network requests. It checks URL authorization boundaries, session/CSRF handling, sample fill-only behavior, partial failures, and unknown PHP. Test-double passes do not establish live target or provider acceptance.

Repair-lab Docker acceptance and scripted playback remain separate:

```bash
DOCKER_CONTEXT=lima-patchpilot-demo uv run --locked --extra dev python -m pytest -p no:cacheprovider -m docker tests/runtime
node src/patchpilot/static/scripts/verify-mock.mjs
uv build
```

The Docker suite exercises actual 3 MiB upload verification, isolated staging, activation, restoration, and project-scoped reset. The opt-in local repair/provider check is documented in [the core guide](src/patchpilot/core/README.md). The [interface guide](docs/design/interface.md) and [frontend guide](src/patchpilot/static/README.md) describe browser checks and optional Playwright/axe setup. Record current live website validation separately, including URL, timestamps, response fingerprints, and actual provider provenance.

`pyproject.toml` and `uv.lock` define reproducible dependencies. No repository-wide formatter or linter policy is currently enforced; `git diff --check` checks whitespace.
