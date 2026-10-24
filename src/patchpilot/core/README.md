# Core repair engine

This package owns PHP advisory policy, assessment fingerprints, approved repair
control, Anthropic proposals, verified recipe reuse, and the real application
coordinator. The API composes `RealRepairService` with the Docker/HTTP bridge and
filesystem stores. See the [demo guide](../../../docs/demo/demo-script.md) for the
complete browser workflow and recorded four-site acceptance.

## Run deterministic checks

From the repository root:

```bash
uv sync --locked --extra dev
uv run --locked --extra dev python -m pytest -p no:cacheprovider tests/core
```

These tests use stateful runtime fakes, temporary stores, and the actual Anthropic
SDK with a mock HTTP transport. They do not deploy containers or spend credits.
They cover policy rejection, stale approvals, staging/live failures, restoration,
checkpoint failure, server-owned approval/session binding, recipe reuse, and
truthful interrupted-run reports. The session-binding mutation test was observed
to fail when its guard was inverted; the implementation was restored afterward.

## Anthropic configuration

Set `ANTHROPIC_API_KEY` and optionally `ANTHROPIC_MODEL` in the ignored local `.env`
or environment. The default model is `claude-sonnet-5-5`. Environment settings take
precedence; dotenv interpolation is disabled, and the placeholder key is rejected.

The planner uses the official SDK and [structured JSON output](https://platform.claude.com/docs/en/build-with-claude/structured-outputs).
It permits only approved image/profile selections, caps output at 1,024 tokens,
uses a maximum 30-second request timeout, and disables SDK retries. It sends
normalized runtime/capability facts and check IDs/results; URLs, deployment
identities, raw failure messages, and credentials are omitted. The controller
validates every proposal independently. Provider errors do not produce fallback
plans or invented usage.

This optional smoke check makes **one real API request** with synthetic upload
requirements. It does not deploy or repair a website:

```bash
uv run --locked --extra dev python tests/core/live_anthropic.py
```

A successful synthetic smoke check and a completed deployment are separate pieces
of evidence. The browser acceptance recorded in the demo guide repaired four
actual local deployments, with two model proposals and two verified recipe uses.

## Integration and evidence

`RealRepairService` issues assessments and approvals, rechecks the frozen policy
and deployment fingerprint, then runs the synchronous `RepairController` in a
worker thread. `_Journal.emit()` waits for the complete checkpoint and ordered
UI event to become durable before activation proceeds. Checkpoint snapshots stay
incomplete until the controller finishes. A multi-site run stays incomplete until
all approved sites finish; each completed site's proof is persisted before it
can seed memory.

Only a model or previously verified recipe with complete, passing live evidence
can become a reusable recipe. Compatibility binds application/configuration
hashes, runtime, capabilities, template/verifier revisions, and approved policy.
A recipe is a proposed plan: every reuse still undergoes staging and live checks.
Provider/source provenance is retained separately for each site.

Startup recovery uses persisted original identity and bounded runtime operations.
An untouched queued run becomes interrupted. Restoration must match the original
identity and pass HTTP checks; its report remains unpatched. Missing recovery
proof blocks further changes. Shutdown drains offloaded work before dependencies
close.

## Runtime contract

The bridge implements `core.ports.Runtime` and `Verifier`. It pins the approved
platform digest, hashes actual container content, stages on a separate loopback
port, and activates the exact tested image/deployment identity. Cleanup is scoped
to the owned run/attempt; restoration verifies the retained original before
removing a replacement.

Verifier phases are `BASELINE`, `STAGING`, `LIVE`, and `RESTORATION`. Every phase
requires runtime version, Apache SAPI, upload-progress configuration, deployment
identity, homepage, valid contact, and invalid contact checks. Upload sites also
require actual 3 MiB byte-count and SHA-256 checks. Missing, duplicate, or failed
results cannot pass the controller gate. Candidate/live expectations require the
patched runtime; baseline/restoration expectations describe the original.

The real Docker suite covers staging, activation, restoration, reset isolation,
and unchanged upload assertions. CI, a production hosting/repository connector,
broad penetration testing, and evaluation benchmarks remain future work.
