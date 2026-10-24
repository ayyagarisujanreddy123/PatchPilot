# PatchPilot Implementation Tasks

The merged components are integrated on `fix/demo-integration`. The [demo guide](../docs/demo/demo-script.md) records an actual four-site browser/Anthropic repair with verified recipe reuse. See [README](../README.md) for working setup and validation commands. Unchecked gates below still require their stated evidence; CI, evaluation comparisons, a recording, public-site connections, and broad penetration testing are not claimed complete. Follow [plan.md](plan.md) for the longer-term architecture and [team-plan.md](team-plan.md) for the original parallel work assignments.

## Phase A: Setup and first real repair

### Task 01: Establish the project toolchain

**Lead:** Teammate 3.

**Description:** Check PATH and installed tools; provision a project-managed Python 3.12 environment, dependency lock, quality tools, and installable package skeleton.

**Acceptance criteria:**

- [ ] Python, uv, Docker client/engine, and machine architecture are recorded; system Python is preserved.
- [ ] A frozen dependency install and package build succeed; runtime files and secrets are ignored.

**Verification:** `uv sync --frozen`; `uv build`; inspect `docker version` and installed Python. Register test markers and the planned lint/type tools.

**Dependencies:** None. **Estimated scope:** Medium, five files.

**Files likely touched:** `pyproject.toml`, `uv.lock`, `.python-version`, `.gitignore`, `src/patchpilot/__init__.py`.

### Task 02: Register the fleet and approved security policy

**Lead:** Sujan (Teammate 2 supplies fleet/image inputs; Teammate 3 owns common fixtures).

**Description:** Define four local targets, two capability groups, image aliases/digests, profiles, ownership labels, and the reviewed advisory policy.

**Acceptance criteria:**

- [ ] Original and fixed PHP/Apache images resolve for the laptop architecture, are pulled, and have recorded provenance/digests.
- [ ] Policy rejects unknown sites/images/profiles and requires the upload-progress mitigation in candidates.

**Verification:** `uv run pytest tests/core/test_policy.py`; inspect both pulled images; confirm fixed-release provenance against PHP announcements.

**Dependencies:** 01. **Estimated scope:** Medium, five files.

**Files likely touched:** `config/fleet.json`, `config/advisories.json`, `src/patchpilot/core/policy.py`, `tests/core/test_policy.py`, `tests/conftest.py`.

### Task 03: Serve one real PHP fixture

**Lead:** Teammate 2.

**Description:** Build a fixed fixture image with homepage, contact validation, and an HTTP runtime/deployment probe. Organization presentation comes from validated fixture settings.

**Acceptance criteria:**

- [ ] Homepage content, valid/invalid contact submissions, and actual serving PHP/SAPI/configuration are observable through HTTP.
- [ ] The fixture binds to loopback, uses temporary state, and contains no real contact delivery or personal data.

**Verification:** `uv run pytest tests/runtime/test_basic_fixture.py`; inspect the homepage and runtime response from the original image.

**Dependencies:** 02. **Estimated scope:** Medium, five files.

**Files likely touched:** `fixtures/Dockerfile`, `fixtures/site/index.php`, `fixtures/site/contact.php`, `fixtures/site/runtime.php`, `tests/runtime/test_basic_fixture.py`.

### Checkpoint A1: Reproducible original environment

- [ ] A clean setup builds and serves one correctly identified original fixture.
- [ ] Policy tests pass and only owned loopback resources exist.
- [ ] Review image identity and capability definitions before deployment work.

### Task 04: Stage immutable candidates through a Docker adapter

**Lead:** Teammate 2.

**Description:** Implement fixed image builds and container inspection, readiness, staging, activation primitives, retained-original handling, and scoped cleanup.

**Acceptance criteria:**

- [ ] A candidate uses an approved base and baked application/configuration content on a separate loopback port; the original keeps serving.
- [ ] Container/image identities and original launch settings are captured; timeouts and cleanup are bounded.

**Verification:** `uv run pytest tests/runtime/test_deployment.py`; inspect bindings and confirm the original address remains available during staging.

**Dependencies:** 03. **Estimated scope:** Small, two files.

**Files likely touched:** `src/patchpilot/runtime/deployment.py`, `tests/runtime/test_deployment.py`.

### Task 05: Verify serving runtime and application behavior

**Lead:** Teammate 2 (Teammate 3 owns shared contracts).

**Description:** Define typed results and a shared HTTP verifier with baseline, candidate, live, and restoration expectations.

**Acceptance criteria:**

- [ ] Fixed-runtime/mitigation assertions use HTTP observations plus deployment identity, not only an image tag or CLI version.
- [ ] Functional checks pass on the original; existing failures and security expectations are distinguished by phase.

**Verification:** `uv run pytest tests/runtime/test_verification.py`; deliberately fail content, contact validation, and deployment identity independently.

**Dependencies:** 04. **Estimated scope:** Medium, three files.

**Files likely touched:** `src/patchpilot/shared/contracts.py`, `src/patchpilot/runtime/verification.py`, `tests/runtime/test_verification.py`.

### Task 06: Complete one approved repair through the CLI

**Lead:** Sujan (Teammate 3 owns package entry-point changes).

**Description:** Connect assessment, explicit CLI approval, a clearly labeled deterministic plan, staging, activation, and final checks for one site. Add the doctor command.

**Acceptance criteria:**

- [ ] The real serving runtime changes at the original address and required behavior still passes.
- [ ] Execution stops on failed prerequisites or unapproved scope; the run reports actual phases and provenance.

**Verification:** `uv run patchpilot doctor`; `uv run pytest tests/core/test_single_repair.py`; manually approve one CLI repair and inspect the live runtime.

**Dependencies:** 05. **Estimated scope:** Medium, five files.

**Files likely touched:** `src/patchpilot/core/assessment.py`, `src/patchpilot/core/controller.py`, `src/patchpilot/core/cli.py`, `pyproject.toml`, `tests/core/test_single_repair.py`.

### Checkpoint A2: First working vertical slice

- [ ] One real runtime upgrade passes unchanged checks after activation.
- [ ] Compare actual elapsed time with the specification's 75-minute target and retain the result.
- [ ] Review the working repair before adding model planning or dashboard polish.

## Phase B: Compatibility and deployment recovery

### Task 07: Verify the real upload capability

**Lead:** Teammate 2.

**Description:** Extend the fixture and verifier to send a benign 3 MiB multipart upload and validate the returned size and content hash.

**Acceptance criteria:**

- [ ] The original 8M/10M upload profile accepts the payload; a 2M candidate fails the actual request.
- [ ] Uploaded bytes are temporary and cannot execute; basic sites remain valid without an upload requirement.

**Verification:** `uv run pytest tests/runtime/test_uploads.py`; compare SHA-256 with the exact sent payload.

**Dependencies:** 06. **Estimated scope:** Medium, four files.

**Files likely touched:** `fixtures/site/upload.php`, `fixtures/site/index.php`, `src/patchpilot/runtime/verification.py`, `tests/runtime/test_uploads.py`.

### Task 08: Reject and revise a failed candidate

**Lead:** Sujan.

**Description:** Add the Planner interface and a deterministic test double; feed structured failures into one revision. Provide an explicitly labeled demo-only seeded profile.

**Acceptance criteria:**

- [ ] A rejected staging candidate leaves the original serving; one revised candidate preserves uploads and the security policy.
- [ ] The controller allows at most two candidates, keeps assertions unchanged, and reports exhaustion accurately.

**Verification:** `uv run pytest tests/core/test_candidate_retry.py`; exercise both successful revision and exhausted attempts.

**Dependencies:** 07. **Estimated scope:** Medium, three files.

**Files likely touched:** `src/patchpilot/core/planner.py`, `src/patchpilot/core/controller.py`, `tests/core/test_candidate_retry.py`.

### Task 09: Restore after a real activation failure

**Lead:** Sujan for recovery behavior; Teammate 2 for Docker operations and runtime tests.

**Description:** Finish activation using the staged image/content identity; inject a labeled failure after the original stops and verify restoration at its original address.

**Acceptance criteria:**

- [ ] The retained original resumes its recorded identity and behavior after failed activation; it remains labeled unpatched.
- [ ] Live-check failure, failed restoration, and cleanup errors have distinct outcomes and retained evidence.

**Verification:** `uv run pytest tests/runtime/test_recovery.py`; demonstrate a real stop/start restoration and cover restoration failure with controlled faults.

**Dependencies:** 08. **Estimated scope:** Medium, five files.

**Files likely touched:** `src/patchpilot/runtime/deployment.py`, `src/patchpilot/core/controller.py`, `src/patchpilot/core/recovery.py`, `tests/runtime/test_recovery.py`, `tests/core/test_recovery.py`.

### Checkpoint B: Failure paths are demonstrated

- [ ] A real 3 MiB upload rejects the seeded incompatibility and passes after revision.
- [ ] Activation failure restores and verifies the original without claiming it is patched.
- [ ] Review attempt bounds, retained originals, and cleanup before enabling durable queued execution.

## Phase C: Durable execution and live model planning

### Task 10: Persist operation intent and evidence

**Lead:** Teammate 3 (Sujan integrates core events).

**Description:** Add versioned run snapshots, append-only events, atomic writes, idempotency records, and the process/operation locking primitives.

**Acceptance criteria:**

- [ ] Deployment intent is durably recorded before side effects; incomplete writes do not become valid success records.
- [ ] Run events retain ordering, provenance, checks, failures, and warnings across reloads of stored data.

**Verification:** `uv run pytest tests/backend/test_storage.py`; inject write failures and validate retained records against schemas.

**Dependencies:** 09. **Estimated scope:** Medium, four files.

**Files likely touched:** `src/patchpilot/backend/storage.py`, `src/patchpilot/shared/contracts.py`, `src/patchpilot/core/controller.py`, `tests/backend/test_storage.py`.

### Task 11: Reconcile interrupted operations

**Lead:** Sujan for interrupted-run recovery; Teammate 3 for persistence/startup plumbing.

**Description:** Inspect incomplete journals and owned Docker resources at startup; serialize repair/reset reservations and reject a second controller process.

**Acceptance criteria:**

- [ ] A restart around original-stop/replacement-start resolves actual state or reports a blocked/recovery-failed outcome without duplicate activation.
- [ ] Concurrent mutations and duplicate intents cannot overlap; unowned resources are never restored or removed.

**Verification:** `uv run pytest tests/backend/test_reconciliation.py`; interrupt the controller around the activation boundary and restart it.

**Dependencies:** 10. **Estimated scope:** Medium, five files.

**Files likely touched:** `src/patchpilot/core/recovery.py`, `src/patchpilot/backend/reconciliation.py`, `src/patchpilot/backend/storage.py`, `src/patchpilot/core/cli.py`, `tests/backend/test_reconciliation.py`.

### Task 12: Produce a repair plan with a real model

**Lead:** Sujan.

**Description:** Use the implemented official Anthropic SDK adapter with the typed plan contract and normalized failure evidence. Local `.env` loading, mocked HTTP checks, and a one-request live synthetic-upload smoke check passed. Real model-driven Docker repair and revision remain required before completing this gate.

**Acceptance criteria:**

- [ ] A live provider returns an allowed image/profile plan and can revise from failed-test evidence; credentials never enter prompts or logs.
- [ ] Invalid output, provider failures, SDK retries, time budgets, and seeded/fallback provenance are handled explicitly.

**Verification:** `uv run pytest tests/core/test_planner.py`; run `uv run pytest -m live_model tests/core/test_live_planner.py` with configured credentials and retain the result. Missing credentials must be reported, not presented as a passing live test.

**Dependencies:** 11; provider/model selection and credentials. **Estimated scope:** Medium, four files.

**Files likely touched:** `src/patchpilot/core/planner.py`, `src/patchpilot/core/README.md`, `tests/core/test_planner.py`, `tests/core/test_live_planner.py`.

### Checkpoint C: Observable autonomous execution

- [ ] Controller interruption and concurrency tests pass.
- [ ] A live model-driven repair has recorded planner provenance, checks, and deployment identity.
- [ ] Review model authority, retry budgets, and recovery evidence before adding memory.

## Phase D: Fleet and verified recipe reuse

### Task 13: Reuse exact verified repair recipes

**Lead:** Sujan (Teammate 3 owns shared contracts and persistence).

**Description:** Implement canonical compatibility keys, provenance, successful-recipe commits, and quarantine after incompatibility.

**Acceptance criteria:**

- [ ] Equivalent sites match despite organization names; changing policy, image/platform, relevant configuration, capabilities, template, or tests invalidates the match.
- [ ] Only live-verified repairs create reusable recipes; every hit still stages and rechecks.

**Verification:** `uv run pytest tests/core/test_recipes.py`; assert no recipe is saved after rejection or restoration.

**Dependencies:** 12. **Estimated scope:** Medium, four files.

**Files likely touched:** `src/patchpilot/core/recipes.py`, `src/patchpilot/shared/contracts.py`, `src/patchpilot/core/controller.py`, `tests/core/test_recipes.py`.

### Task 14: Execute the four-site fleet sequentially

**Lead:** Sujan.

**Description:** Start the full manifest fleet and run an approved site set through the controller, retaining per-site outcomes and real memory metrics.

**Acceptance criteria:**

- [ ] Both capability pairs repair through real Docker/HTTP operations and matching recipes are reused with fresh checks.
- [ ] The fleet reserves one operation, processes sites sequentially, revalidates each site's approval, and retains failed outcomes.

**Verification:** `uv run pytest tests/core/test_fleet.py`; inspect the four original addresses and recipe provenance.

**Dependencies:** 13. **Estimated scope:** Medium, three files.

**Files likely touched:** `src/patchpilot/core/fleet.py`, `src/patchpilot/core/cli.py`, `tests/core/test_fleet.py`.

### Task 15: Reset only the owned demonstration fleet

**Lead:** Teammate 2 (Sujan integrates CLI hooks).

**Description:** Restore the original fleet from registered snapshots, optionally clear recipes, and preserve all completed run records.

**Acceptance criteria:**

- [ ] Repeated reset returns the known originals, invalidates stale assessments/approvals, and leaves unrelated resources untouched.
- [ ] Reset and repair cannot overlap; cleanup and partial reset failures remain visible.

**Verification:** `uv run pytest tests/runtime/test_reset.py`; compare resource ownership and run history before and after two resets.

**Dependencies:** 14. **Estimated scope:** Medium, three files.

**Files likely touched:** `src/patchpilot/runtime/reset.py`, `src/patchpilot/core/cli.py`, `tests/runtime/test_reset.py`.

### Checkpoint D: Repeatable fleet demonstration

- [ ] Four sites repair and an exact recipe match is reused and independently checked.
- [ ] Reset restores originals while preserving the evidence trail.
- [ ] Review fleet results and invalidation cases before exposing HTTP mutation routes.

## Phase E: Owner workflow

### Task 16: Expose assessments, approvals, and run resources

**Lead:** Teammate 3.

**Description:** Add the typed API, a lifespan-owned worker, local request guards, stale-approval detection, persisted idempotency, and consistent errors.

**Acceptance criteria:**

- [ ] Assessment → approval → accepted run works for registered sites; duplicate submission returns the existing resource and changed payloads conflict.
- [ ] Unknown/stale/unauthorized requests and overlapping reset/repair fail before deployment side effects; progress survives request completion and browser refresh.

**Verification:** `uv run pytest tests/backend/test_runs.py`; verify OpenAPI, lifespan shutdown/startup, `202/404/409/422`, and same-origin guards.

**Dependencies:** 15. **Estimated scope:** Medium, four files.

**Files likely touched:** `src/patchpilot/backend/app.py`, `src/patchpilot/backend/api.py`, `src/patchpilot/shared/contracts.py`, `tests/backend/test_runs.py`.

### Task 17: Build fleet review and repair progress screens

**Lead:** Teammate 4 (Teammate 3 owns backend routes).

**Description:** Render the four-site dashboard, assessment/approval details, and real phase/check progress with accessible controls and polling.

**Acceptance criteria:**

- [ ] A user can inspect the proposed changes, approve one scope, and follow actual checks without additional technical setup screens for registered fixtures.
- [ ] Refresh restores the active view; keyboard navigation works; seeded faults are restricted to clearly labeled demo operator controls.

**Verification:** `uv run pytest tests/ui/test_dashboard.py`; manually review narrow/desktop layouts and the approval boundary in a real browser.

**Dependencies:** 16. **Estimated scope:** Medium, five files.

**Files likely touched:** `src/patchpilot/web/templates/dashboard.html`, `src/patchpilot/web/static/app.js`, `src/patchpilot/web/static/style.css`, `src/patchpilot/backend/api.py`, `tests/ui/test_dashboard.py`.

### Task 18: Present evidence reports and run history

**Lead:** Teammate 3 for API; Teammate 4 for all UI files.

**Description:** Add bounded event/report/history API responses and a report view showing actual security, functional, recovery, and recipe evidence.

**Acceptance criteria:**

- [ ] Verified repair, rejected candidate, restored original, and recovery failure display distinct outcomes; fixed vulnerabilities and mitigations are identified separately.
- [ ] History/report links survive reset and refresh; untrusted text is escaped and secrets are absent.

**Verification:** `uv run pytest tests/backend/test_reports.py tests/ui/test_report.py`; inspect successful and failed reports in the browser.

**Dependencies:** 17. **Estimated scope:** Medium, five files.

**Files likely touched:** `src/patchpilot/web/templates/report.html`, `src/patchpilot/backend/api.py`, `src/patchpilot/web/static/app.js`, `tests/backend/test_reports.py`, `tests/ui/test_report.py`.

### Checkpoint E: Complete owner journey

- [ ] The dashboard supports assessment → approval → repair → evidence for the full fleet.
- [ ] Refresh, failure messages, and recovery outcomes remain accurate.
- [ ] Review browser behavior and reports before release verification.

## Phase F: Release verification

### Task 19: Exercise policy and request abuse cases

**Lead:** Sujan (Teammate 3 owns request guards).

**Description:** Test arbitrary targets, model commands, hostile text, image/profile tampering, unsafe reset paths, cross-origin requests, and deadline exhaustion.

**Acceptance criteria:**

- [ ] Rejected inputs cannot reach Docker, change verification rules, leak credentials, or affect unowned resources.
- [ ] Timeouts, unknown Docker outcomes, and resource limits remain bounded and observable.

**Verification:** `uv run pytest tests/core/test_policy_abuse.py tests/backend/test_request_guards.py`; inspect request guards and actual container bindings.

**Dependencies:** 18. **Estimated scope:** Medium, four files.

**Files likely touched:** `src/patchpilot/core/policy.py`, `src/patchpilot/backend/app.py`, `tests/core/test_policy_abuse.py`, `tests/backend/test_request_guards.py`.

### Task 20: Establish repeatable checks and contributor setup

**Lead:** Teammate 3.

**Description:** Add CI for lint/types/build, deterministic tests, real Docker integration, and browser tests. Document setup, provider configuration, recovery, proposed-to-real commands, and dependency auditing.

**Acceptance criteria:**

- [ ] A clean environment installs the frozen lock and runs required checks with Docker/browser prerequisites; missing prerequisites do not silently pass those gates.
- [ ] Live-provider tests are separately configured and their release evidence is required; setup and accepted architectural choices are documented.

**Verification:** Run CI and documented setup from a clean environment; run Ruff, mypy, `uv build`, deterministic pytest suites including `uv run pytest -m 'docker and not live_model' tests`, and the locked-dependency audit. Retain a separately configured live-model acceptance result.

**Dependencies:** 19. **Estimated scope:** Medium, four files.

**Files likely touched:** `.github/workflows/ci.yml`, `README.md`, `pyproject.toml`, `docs/decisions/0001-local-controller.md`.

### Task 21: Evaluate and rehearse the complete demonstration

**Lead:** Sujan (Teammate 2 owns runtime checks; Teammate 4 owns demo presentation).

**Description:** Add an evidence-producing comparison/rehearsal harness, run both memory arms, record separate injected-fault demonstrations, and prepare the submission recording.

**Acceptance criteria:**

- [ ] Equivalent reset fleets, identical tests, pre-pulled images, fresh conversations, and included failures produce inspectable raw results and provenance.
- [ ] Two complete dashboard run/reset rehearsals and a usable recording satisfy all completion criteria in the plan.

**Verification:** `uv run patchpilot evaluate --output var/evaluations/latest`; `uv run pytest tests/runtime/test_rehearsal.py`; follow the demo script twice and inspect the recording.

**Dependencies:** 20. **Estimated scope:** Medium, five files.

**Files likely touched:** `src/patchpilot/core/cli.py`, `scripts/rehearse.py`, `docs/demo/demo-script.md`, `docs/evaluation.md`, `tests/runtime/test_rehearsal.py`.

### Checkpoint F: Prototype ready for review

- [ ] All required automated checks and the live-model acceptance run pass with retained evidence.
- [ ] Four-site repairs, upload rejection/revision, exact recipe reuse, and deployment restoration are demonstrated.
- [ ] Two run/reset rehearsals and a usable recording exist; unresolved limits are stated accurately.
- [ ] Human review precedes any merge or production deployment. Production workstreams P1–P6 remain separately gated in the plan.
