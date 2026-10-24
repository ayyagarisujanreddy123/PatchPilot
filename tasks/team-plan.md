# Four-Person Hackathon Work Plan

Team: **Sujan plus three teammates**. Nicholas, Teammate 3, and Teammate 4 are role labels until names are supplied.

Deliver the four-site local prototype in [plan.md](plan.md). Use [todo.md](todo.md) for acceptance criteria. The assignments below define who edits each file; task dependencies are integration gates, not a reason to wait before starting isolated work.

## 1. Team assignments

| Person | Responsibility | Start immediately | Finished contribution |
| --- | --- | --- | --- |
| **Sujan — core product engineer and technical lead** | **Security assessment, core repair engine, AI planner, policy enforcement, recovery decisions, verified repair memory, fleet execution, and final integration** | Code assessment/policy and the bounded controller against fake deployment/verifier/planner implementations. | Sujan's working engine determines what needs repair and drives real planning, staging, verification, revision, activation, recovery, and reuse across sites. |
| **Nicholas — runtime and verification** | Docker fixtures, deployment adapter, real HTTP checks, restoration, and reset | Build the first PHP fixture and verify the original/fixed image availability. | Four local sites, immutable candidates, real upload tests, same-address activation, and verified original restoration. |
| **Teammate 3 — backend and platform** | Shared contracts, package setup, FastAPI, approvals, persistence, locks, restart reconciliation, and CI | Ship the package skeleton and shared contracts first; develop API behavior against a fake repair service. | A reproducible backend that accepts approved work once, persists progress, survives restart, and serves the UI. |
| **Teammate 4 — UI owner** | **All dashboard UI, styles, browser behavior, report screens, accessibility, and demo presentation** | Build the screens using clearly labeled local mock responses matching section 4. | A usable fleet → assessment → approval → progress → report experience connected to the real API. |

Sujan has the largest product implementation scope. He codes the engine that makes PatchPilot work: determining which issue applies, choosing an allowed repair, advancing phases, interpreting test results, deciding when to revise or restore, and recording a verified outcome. Runtime operations and HTTP verification are separate implementations that his controller calls through fixed interfaces. Backend routes invoke his service; they do not implement a second repair engine.

## 2. Exclusive file ownership

The repository has no application code yet, so adopt these separate packages now. Each path has one editor. Implement shared-file requests through the assigned owner.

| Owner | Exclusive paths |
| --- | --- |
| **Sujan** | `src/patchpilot/core/`, `config/advisories.json`, `tests/core/`, `scripts/rehearse.py`, `docs/evaluation.md`, `tasks/`, root `PatchPilot_*.md` specifications |
| **Nicholas** | `src/patchpilot/runtime/`, `fixtures/`, `config/fleet.json`, `tests/runtime/` |
| **Teammate 3** | `src/patchpilot/backend/`, `src/patchpilot/shared/`, `src/patchpilot/__init__.py`, `tests/backend/`, `tests/conftest.py`, `pyproject.toml`, `uv.lock`, `.python-version`, `.gitignore`, `.github/`, `README.md`, `docs/decisions/` |
| **Teammate 4** | `src/patchpilot/web/`, `tests/ui/`, `docs/demo/` |

Rules that keep edits separate:

1. Teammate 4 owns every HTML, CSS, browser JavaScript, and UI mock file. Backend integration changes routes/context in `backend/`, not UI files.
2. Teammate 3 alone edits shared models, dependency manifests, lockfiles, common test fixtures, and CI. Request additions in a PR comment; do not independently regenerate `uv.lock`.
3. Sujan owns advisory policy; Nicholas owns the fleet manifest. Exchange image digests and site requirements instead of editing each other's configuration file.
4. Put each person's tests under their owned test directory. Keep private test doubles there; only Teammate 3 edits `tests/conftest.py`.
5. Sujan updates the shared planning checklists after merges. Other teammates report progress in their PR descriptions, avoiding four people editing this file or `todo.md`.
6. Leave `AGENTS.md` unchanged. Add new files only inside an owned path; agree on an owner before adding a new shared root file.

Exclusive ownership prevents planned same-file edits. Shared contracts and frequent integration are still required to catch behavior mismatches.

## 3. Work packets

### Sujan: implement the core product

**Branch:** `feature/sujan-core`

**Primary files:** `core/assessment.py`, `core/controller.py`, `core/planner.py`, `core/policy.py`, `core/recovery.py`, `core/recipes.py`, `core/fleet.py`, `core/cli.py`.

**First PRs:** assessment/policy plus focused tests, followed by controller transitions using private fakes. Cover a passing candidate, failed staging, one revision, and exhausted attempts. This can begin before Docker, the API, or UI is ready.

**Then:** integrate Nicholas's adapter/verifier; code activation/recovery decisions and interrupted-run recovery; add the real Strands planner; implement exact compatibility keys and recipe eligibility; process the fleet sequentially. Teammate 3 provides persistence through store interfaces and invokes Sujan's recovery service at startup. Wire CLI commands to the same engine.

**Done when:** a real approved repair passes live checks; failures produce accurate rejection/restoration outcomes; matching sites reuse a verified recipe with fresh checks. Model output cannot change tests or execute arbitrary commands. Sujan leads integration and the technical demo explanation.

**Task leads:** 02, 06, 08, 09, 11, 12, 13, 14, 19, 21. In 09/11, Nicholas implements Docker primitives and Teammate 3 implements persistence/startup plumbing; Sujan implements the recovery behavior.

### Nicholas: Docker, fixtures, and verification

**Branch:** `feature/runtime-verification`

**Primary files:** `runtime/deployment.py`, `runtime/verification.py`, `runtime/reset.py`, `runtime/fixture_cli.py`, `fixtures/Dockerfile`, `fixtures/site/*.php`, `config/fleet.json`.

**First PR:** one working homepage/contact fixture with an HTTP runtime probe, plus its tests and startup instructions. Report original/fixed image identities and platform digests to Sujan. Start with the fixture even while shared Python contracts are being prepared.

**Then:** implement stage/activate/restore/cleanup operations, the real 3 MiB multipart verification, the second fixture capability group, four-site provisioning, and scoped reset. Provide a small standalone fixture CLI; Sujan integrates its functions into the main CLI.

**Done when:** the original remains available during staging, activation uses the tested content at the original address, a failed activation can restore the recorded original, and reset affects only owned fixtures. Real HTTP evidence must include runtime/SAPI, contact behavior, upload size/hash, and deployment identity.

**Task leads:** 03, 04, 05, 07, 15. Own runtime portions of 09; support 02, 06, 11, 14, and 21.

### Teammate 3: backend, shared foundation, and persistence

**Branch:** `feature/backend-platform`

**Primary files:** `shared/contracts.py`, `shared/ports.py`, `backend/app.py`, `backend/api.py`, `backend/storage.py`, `backend/reconciliation.py`, project configuration, and CI.

**First PRs — merge these first:** package setup/locked dependencies, then shared contracts/interfaces and a health route. Keep each PR small; these should not wait for a completed backend. Add shared files requested by the other three people through follow-up PRs.

**Then:** expose Sujan's assessment/repair service through approvals/run resources, initially using a private fake service; implement atomic journals and JSON snapshots, one lifespan-owned worker, idempotency/busy reservations, and startup plumbing that calls Sujan's interrupted-run recovery service. Serve Teammate 4's pages/static files and supply their documented template context.

**Done when:** duplicate requests reuse the original run, stale approvals fail before deployment, run/reset cannot overlap, events survive refresh/restart, and CI exercises the real required checks. All disk writes and coordination are implemented here; Sujan owns recipe-selection and state-machine decisions.

**Task leads:** 01, 10, 16, 18, 20. Own backend portions of 11 and shared contracts in 02, 05, 06, 13, 17, and 19.

### Teammate 4: all UI and demo presentation

**Branch:** `feature/dashboard-ui`

**Primary files:** `web/templates/dashboard.html`, `web/templates/report.html`, `web/static/app.js`, `web/static/style.css`, `web/dev/`, `tests/ui/`, `docs/demo/`.

**First PR:** a responsive dashboard with four sites, assessment/approval, repair progress, and result/report states, driven by labeled local mock data. Include a local preview procedure. No live API dependency is needed to begin.

**Then:** replace the mock data source with the fixed API contract; add history, real checks/provenance, refresh recovery, keyboard access, and clear terminal outcomes. Keep mock mode visibly labeled and outside the real demo path. Backend endpoint implementations belong to Teammate 3.

**Done when:** a user can complete the real owner journey; failed staging, restored original, and recovery failure look distinct; progress comes from real records; browser checks pass. Prepare the presenter walkthrough and capture a usable recording after the real fleet rehearsals.

**Task leads:** 17. Own the UI portions of 18 and 21; Teammate 3 owns their backend portions and Sujan owns evaluation logic.

## 4. Shared contract version 1

Freeze these interfaces at kickoff. Teammate 3 implements them in `shared/`; Sujan reviews changes. Consumers request revisions rather than editing shared types. Python properties use `snake_case`, JSON fields use `camelCase`, and state/source values use uppercase enums.

### Registered targets

| Site ID | Local address | Required behavior |
| --- | --- | --- |
| `pantry-a` | `http://127.0.0.1:8081` | Homepage and valid/invalid contact submissions |
| `pantry-b` | `http://127.0.0.1:8082` | Same template/capabilities as `pantry-a` |
| `clinic-a` | `http://127.0.0.1:8083` | Homepage, contact, and real 3 MiB upload |
| `clinic-b` | `http://127.0.0.1:8084` | Same template/capabilities as `clinic-a` |

These are planned bindings, not currently running sites. Nicholas checks availability before starting them. If a port is occupied, report it and update the manifest/UI mocks through their owners; never stop an unrelated service. Candidate ports are separately allocated on loopback.

### Module boundaries

| Owner | Interface | Contract |
| --- | --- | --- |
| Sujan | `Core.assess(snapshot, checks, policy) -> Assessment` | Match the observed runtime to approved advisories; distinguish applicability, baseline failure, and unsupported environments. |
| Sujan | `Planner.propose(context, failures) -> RepairPlan` | Return only target-image alias, configuration-profile ID, and rationale. Controller assigns provenance. |
| Nicholas | `Runtime.inspect(site) -> DeploymentSnapshot` | Return actual original identity/settings and observed serving information. |
| Nicholas | `Runtime.stage(site, plan, run_id, attempt) -> CandidateSpec` | Return candidate endpoint, immutable content/image identity, and resource handle. |
| Nicholas | `Verifier.check(site, deployment, phase) -> list[CheckResult]` | Same assertions, with baseline/candidate/live/restoration expectations. |
| Nicholas | `Runtime.activate(site, candidate, original) -> DeploymentSnapshot` | Use the tested content at the original address; raise a typed failure if uncertain. |
| Nicholas | `Runtime.restore(site, original) -> DeploymentSnapshot` | Restore the retained original; verifier independently checks restoration. |
| Nicholas | `Runtime.cleanup(candidate) -> CleanupResult` | Remove owned staging resources and report any failures. |
| Teammate 3 | `RunStore` / `RecipeStore` / `EventSink` | Persist typed records atomically and append ordered events; expose no raw paths to the model. |
| Sujan | `RepairService.run(approval, dependencies) -> RunRecord` | Own bounded state transitions, recipe eligibility, retries, activation gates, and event production. |
| Sujan | `Core.recover_interrupted(record, dependencies) -> RunRecord` | Decide recovery within the recorded approval and observed state; backend startup invokes this instead of inventing its own recovery rules. |
| Teammate 3 | `submit_run(approval_id, idempotency_key) -> run reference` | Validate authority and reserve work; HTTP request completion does not stop the worker. |

The backend composition layer supplies runtime, verifier, planner, stores, and event sink to the controller. Core and runtime code depend on shared interfaces, not on backend route handlers. Blocking operations have explicit timeouts; the backend runs them off the request event loop.

### UI API

Teammate 3 implements the endpoints in the technical plan. Teammate 4 consumes them without changing their schemas:

- `GET /api/sites` and `POST /api/sites/{siteId}/assessments`.
- `POST /api/approvals`; `POST /api/runs` with `{ "approvalId": "...", "memoryEnabled": true }` and an `Idempotency-Key`.
- `GET /api/runs/{runId}`, `/events?after=<sequence>`, `/report`, and paginated `GET /api/runs`.
- `POST /api/resets` and `GET /api/resets/{resetId}` for labeled demo operator controls.

Mutating requests include the local session/CSRF headers agreed with Teammate 3. An accepted run returns `202` with `runId` and `statusUrl`. Errors use `{ "error": { "code": "...", "message": "...", "details": {} } }`. Lists use `{ "items": [], "nextCursor": null }`; event polling uses `{ "items": [], "nextSequence": 0 }`. Teammate 3 supplies `csrf_token` in the HTML template context.

Freeze the following additional UI fields in shared contracts before replacing mocks:

| Resource | Fields consumed by the UI |
| --- | --- |
| Site list item | `siteId`, `displayName`, `baseUrl`, `capabilities`, `assessmentState`, `lastRunId` |
| Assessment response | `assessmentId`, `siteId`, `fingerprint`, `policyRevision`, `applicability`, `currentRuntime`, `proposedChanges`, `requiredChecks`, `canRepair`, `blockedReason` |
| Approval request | `assessments`: list of `{assessmentId, fingerprint}`; `policyRevision` |
| Approval response | `approvalId`, `siteIds`, `expiresAt` |
| Event item | `sequence`, `timestamp`, `siteId`, `state`, `message`, `check`: nullable `CheckResult` |
| Repair report | `runId`, `state`, `siteResults`, `checks`, `changes`, `securityResults`, `recovery`, `provenance`, `warnings` |

Sujan supplies assessment semantics; Teammate 3 owns their schemas/serialization. Server-side records determine authority and approval freshness; client fingerprints alone grant no access. Teammate 4 requests any additional UI fields through those owners rather than renaming fields locally.

Illustrative run response for UI development; values below are mock data, not observed results:

```json
{
  "schemaVersion": 1,
  "runId": "mock-run-001",
  "siteIds": ["pantry-a"],
  "currentSiteId": "pantry-a",
  "state": "VERIFYING",
  "attempt": 1,
  "planSource": "MODEL",
  "checks": [
    {
      "checkId": "homepage",
      "siteId": "pantry-a",
      "phase": "STAGING",
      "passed": true,
      "message": "Expected organization content received",
      "durationMs": 12
    }
  ],
  "warnings": [],
  "error": null
}
```

States: `QUEUED`, `ASSESSING`, `PLANNING`, `STAGING`, `VERIFYING`, `REVISING`, `ACTIVATING`, `LIVE_VERIFYING`, `RESTORING`, `VERIFIED`, `REJECTED`, `BLOCKED`, `RESTORED`, `RECOVERY_FAILED`, `INTERRUPTED`. Sources: `MODEL`, `VERIFIED_RECIPE`, `DETERMINISTIC_FALLBACK`, `SEEDED_DEMO`, `TEST_DOUBLE`; source is nullable before planning. `RESTORED` means the original is back and the security repair remains unresolved. A fleet failure must retain per-site outcomes and never label the entire fleet verified.

## 5. Parallel start and integration order

Use relative checkpoints rather than waiting for each numbered task to finish globally. Targets depend on the remaining hackathon time and tool readiness.

| Checkpoint | Sujan | Nicholas | Teammate 3 | Teammate 4 |
| --- | --- | --- | --- | --- |
| **Start now** | State-machine tests with fakes | First PHP fixture and image checks | Package/contracts bootstrap PR | Screens and labeled JSON mock responses |
| **First shared base; target 20–30 minutes** | Adopt shared interfaces | Adopt shared interfaces | Merge bootstrap to `main` | Match shared JSON fields |
| **First real repair; 75-minute specification target** | Call real adapter and enforce gates | Supply candidate/live verification | Supply persisted events/service wiring as available | Finish approval/progress states |
| **Core demo complete** | Live AI, one revision, recipe reuse | Four sites, real upload, restoration/reset | Real API, lock/idempotency, recovery records | Connect real API and report outcomes |
| **Before submission** | Lead fleet/evaluation rehearsals | Verify originals/reset and cleanup | Run CI and document clean setup | Verify browser flow and record the demo |

Merge order: **backend bootstrap → runtime fixture/adapter → core first repair → backend real service integration → UI real API integration → AI/reuse/recovery evidence and final checks**. Ship small follow-up PRs throughout; runtime, core, backend, and UI development all begin at kickoff.

Keep fakes private to tests or visibly labeled development previews. A task is complete only when its real integration acceptance criteria pass. Preserve the technical plan's verification gates even when their implementation is parallelized.

## 6. Git workflow

Everyone clones the same repository and creates their assigned branch:

```bash
git clone https://github.com/ayyagarisujanreddy123/PatchPilot.git
cd PatchPilot
git switch -c feature/sujan-core
```

Replace the branch with your assignment. For an existing clone, start from an up-to-date `main` with `git pull --ff-only` before creating the branch.

Commit only your owned files, push your branch, and open a small PR into `main`:

```bash
git add src/patchpilot/core tests/core config/advisories.json
git commit -m "feat: add bounded repair controller"
git push -u origin HEAD
```

The staging example is Sujan's; each teammate uses their own paths and stages only files they created or changed. No one uses `git add .` to collect another person's local work.

Before the next PR, commit your work, run `git fetch origin`, and merge `origin/main` into your feature branch. Do not merge teammates' feature branches into each other or force-push `main`. Each branch has one writer. Sujan coordinates merges; Nicholas reviews Sujan's core changes. Each PR lists its contract dependencies, checks run, and remaining integration limits; UI PRs include screenshots.

## 7. Shared completion gate

- [ ] A real model-driven runtime repair passes security and website checks at the original address.
- [ ] A seeded bad candidate fails the real 3 MiB upload test; one revised candidate passes unchanged assertions.
- [ ] An activation failure restores and verifies the original while reporting the repair unresolved.
- [ ] Four sites complete sequentially; an exact verified recipe is reused and independently checked.
- [ ] The real UI shows approval, checks, provenance, evidence, and accurate failure/recovery outcomes.
- [ ] Duplicate requests, run/reset overlap, and interrupted activation have tested outcomes.
- [ ] Automated checks pass; two complete run/reset rehearsals and a usable recording exist.

Track production hosting, identity, and stateful recovery separately under the production roadmap. The hackathon deliverable is the verified local four-site system.
