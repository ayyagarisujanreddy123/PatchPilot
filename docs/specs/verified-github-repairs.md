# Connected PHP repairs

## First supported flow

Continue from a real website assessment. Connect an explicitly selected GitHub
repository through the local operator's configured GitHub account. Require push
permission and a same-origin `/.well-known/patchpilot.json` deployment marker
containing `repository` (`owner/name`), `commit` (40-character SHA), and `siteId`.
Match the marker to the repository default branch HEAD and `.patchpilot.json`.
Explain that this is declared identity, not independent build attestation.

The repository manifest declares `schemaVersion:1`, `siteId`, `documentRoot`,
`phpIni`, supported `capabilities` (`homepage`, `contact`, `upload`), and the
contact/upload PHP paths. Homepage is mandatory. Owner-selected checks are bound
to the connection. Contact uses the supplied fixture-compatible JSON contract;
upload verifies a real 3 MiB payload's size and SHA-256.

Fetch regular source blobs at the pinned commit with strict path/count/size
limits. Do not run repository scripts, package installers, or Dockerfiles. Stage
PHP in a trusted digest-pinned container with no network, credentials, host socket,
or writable source mount; enforce CPU/memory/process/time limits. Trusted verifier
code sends actual loopback HTTP requests from inside this sandbox.

Anthropic receives only normalized runtime/check/configuration facts and proposes
up to four allowlisted PHP settings: `display_errors=Off`,
`display_startup_errors=Off`, `log_errors=On`, `expose_php=Off`. Preserve every
other setting, including upload limits. Validate all output; never execute model
commands or let it change assertions. Stream real progress. Reject failed baseline
behavior, incomplete checks, invalid proposals, or failing candidates.

Persist the exact one-file diff and baseline/candidate evidence before offering
**Create pull request**. Publication is a separate explicit mutation. Revalidate
the base commit, use a deterministic job branch, reconcile retries, create a draft
PR with the evidence, and never force-update existing refs or merge automatically.
Do not claim the live website was repaired. Keep partial evidence on failures.

## API contract

- `GET /api/repository-connections/status`: local GitHub availability/login.
- `POST /api/repository-connections {assessmentId,repositoryUrl,capabilities}`:
  returns a session-owned connection; same-origin/CSRF protected.
- `GET /api/repository-connections?assessmentId=...`: issuing session connections.
- `POST /api/repository-repairs {connectionId}`: 202 `{repairId,statusUrl}`.
- `GET /api/repository-repairs/{id}` and collection: owned report/history.
- `POST /api/repository-repairs/{id}/pull-request`: explicit, idempotent publication.

Reuse exclusive operation admission and durable jobs; failed/interrupted work must
not fabricate results. UI keeps the compact report and progressively reveals
connection, selected business checks, real progress, diff/proof, and PR action.

## Validation

Use mocked transport for permission, URL/marker/SHA binding, size/path/secret
boundaries, stale bases, invalid model output, failing checks, session isolation,
CSRF and publication retry tests. Real acceptance uses a dedicated owned PHP demo
repository/deployment, actual Anthropic, isolated PHP checks, and a draft GitHub
pull request. Existing public scans and the separate repair lab stay functional.
