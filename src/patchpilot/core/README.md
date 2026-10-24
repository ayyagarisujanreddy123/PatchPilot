# Core repair engine

Sujan owns this package. It contains upstream PHP policy validation, security assessment, approval fingerprints, repair orchestration, and the Anthropic planner. Docker, HTTP probes, durable storage, API routes, and UI implementations are supplied by the other workstreams.

## Run the core tests

From the repository root, with uv available:

```bash
PYTHONPATH=src uv run --no-project --python 3.12 --with pytest==9.1.1 --with anthropic==2.3.0 --with python-dotenv==1.2.4 python -m pytest -p no:cacheprovider --import-mode=importlib tests/core
```

These tests use private adapter fakes and the actual Anthropic SDK with an HTTP mock transport. They neither deploy Docker containers nor spend API credits. Package setup and locked dependencies remain owned by Teammate 3; add `anthropic==2.3.0` and `python-dotenv==1.2.4` to that bootstrap.

## Anthropic configuration

The local, Git-excluded `.env` contains these settings:

```dotenv
ANTHROPIC_API_KEY=your-anthropic-api-key-here
ANTHROPIC_MODEL=claude-sonnet-5-5
```

Replace the placeholder locally. Environment variables override file values. `AnthropicPlanner.from_environment()` reads only these settings, without executing/interpolating the file or modifying the process environment. Placeholder keys are rejected before a request. The API destination is fixed to `https://api.anthropic.com`.

The default model is configurable and listed in the [Anthropic model reference](https://platform.claude.com/docs/en/models/overview). The planner uses [structured JSON output](https://platform.claude.com/docs/en/build-with-claude/structured-outputs), a 1,024-token output cap, at most 30 seconds per SDK request, and zero SDK retries. It sends normalized runtime/capability data and check IDs/pass flags; site URLs, deployment identities, raw failure messages, and credentials are omitted. The controller independently enforces policy after planning.

The following opt-in smoke check makes **one real API request** using a labeled synthetic upload scenario. It does not repair or deploy a website:

```bash
PYTHONPATH=src uv run --no-project --python 3.12 --with anthropic==2.3.0 --with python-dotenv==1.2.4 python tests/core/live_anthropic.py
```

It prints the provider/model, selected profile, request count, and token usage. A refusal, truncated response, invalid choice, or provider failure produces a failed result rather than a fallback. Call `planner.close()` when the backend shuts down.

## Verification recorded on 24 October 2026

- 79 deterministic tests passed on Python 3.12.15; Ruff lint/format checks and strict mypy passed.
- A mutation of the approval-expiry condition caused its regression test to fail; the original controller was restored byte-for-byte.
- The live synthetic-upload smoke check passed using `claude-sonnet-5-5`: one request, `preserve_uploads` selected, 764 input tokens and 163 output tokens. This verifies provider access and the proposal contract; no website was deployed by that check.

## Backend integration

Use the frozen value objects and interfaces in `domain.py`, `policy.py`, and `ports.py`. Teammate 3's shared/Pydantic schemas adapt these core objects to the camelCase API; core repair rules stay in this package.

1. Load `config/advisories.json` with the trusted registered-site IDs. Resolve the approved platform image digest through the runtime workstream and pass it as `approved_image_digest`. The checked-in digest is intentionally unresolved; execution fails closed until it is provided.
2. Obtain an actual `DeploymentSnapshot` and phase-aware verifier results. Call `assess(...)` to produce the finding and fingerprint.
3. Build an `Approval` from a server-side owner approval, binding the fingerprint, policy revision, target alias, permitted profiles, and timezone-aware expiry. A caller-created data object is not proof of ownership; the backend must authenticate and look up the approval.
4. Instantiate `RepairController(policy, runtime, verifier, planner, journal)` and call `run(site, approval, run_id=...)` from the single background worker. The synchronous engine belongs off the API event loop.
5. Persist `RunEvent` checkpoints. `EventSink.emit()` must return only after the checkpoint is durable and must raise on failure. Activation intent includes the retained original, candidate identity, approved scope, plan source, and current evidence.
6. Use the result state and `evidence_complete` flag when releasing the backend's busy reservation. Incomplete evidence requires reconciliation. `RESTORED` is an unpatched original; `RECOVERY_FAILED` has no verified final snapshot.

Model provenance, provider message ID, and token usage are carried by `ProposedPlan` in journal events. `AnthropicPlanner.request_count` counts SDK request attempts, including failed attempts; it does not invent usage for failed requests. Recipe reuse and live-provider acceptance are separate remaining milestones.

## Runtime integration

Teammate 2 implements `Runtime` and `Verifier` from `ports.py`:

- Return normalized core `DeploymentSnapshot`/`Candidate` objects, with actual serving observations and immutable content identities. Keep raw Docker/HTTP responses out of core evidence.
- Staging uses a separate loopback port, the original application content, the approved base digest, and the chosen registered profile. Live activation must preserve the candidate's snapshot identity while using the original address.
- `cleanup(site, run_id, attempt, timeout_s=...)` removes only staging resources owned by that run/attempt. It must also handle partial staging failures where no candidate handle returned. Never remove the active replacement or retained original through this operation.
- `restore(...)` inspects/reconciles actual container state, stops the failed replacement when necessary, and restarts the retained original. The core independently checks its identity and functional results.
- Honor the supplied operation timeout. The engine stops ordinary repair operations at its run deadline; emergency restoration and staging cleanup retain their own bounded timeouts. Total wall-clock and interrupted-worker recovery must be verified with the real runtime/backend integration before those acceptance gates are complete.

Verifier phases are `BASELINE`, `STAGING`, `LIVE`, and `RESTORATION`. Every phase requires `runtime_version`, `sapi`, `upload_progress`, `deployment_identity`, `homepage`, `contact_valid`, and `contact_invalid`; upload sites additionally require `upload_size` and `upload_hash`. Baseline/restoration expectations describe the original runtime. Candidate/live expectations require the patched runtime and mitigation. Missing, duplicated, false, or empty results never pass the core gate.

## Remaining work

The pure core paths and Anthropic request contract are implemented, and the live planner smoke check passed. Real Docker/HTTP execution, server-issued approvals and durable journals, restart reconciliation, verified recipe storage/reuse, fleet execution, and full CLI wiring still require the corresponding implementation milestones. The live API smoke check and mocked transport tests are recorded separately from real website repair acceptance.
