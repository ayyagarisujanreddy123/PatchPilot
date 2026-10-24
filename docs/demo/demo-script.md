# PatchPilot Demo Guide

## What the demo proves

Enter a registered website URL, assess its serving PHP runtime and configuration,
review the proposed repair, approve it, and watch staging and live checks. The
controller changes only the approved image/configuration profiles. It retains the
original deployment for verified restoration.

This prototype assesses a reviewed PHP advisory policy on four local fixtures.
It does not perform a broad penetration test, connect arbitrary public websites,
modify application source, or open repair PRs. Repairing a real website requires an
authorized deployment or repository connection in a later integration.

## Start

Follow the installation and Docker context instructions in [README](../../README.md).
Run one controller on `http://127.0.0.1:8765`. Keep the ignored `.env` local.

1. Open the dashboard and confirm **Real local fixtures**.
2. Select **Prepare local fixtures** if the controller is not prepared. The first
   preparation pulls images; later preparation can reuse locally verified digests.
3. Enter `http://127.0.0.1:8081` and select **Assess site**, or choose
   **Assess & review fleet repair** to demonstrate all four sites.
4. Review the observed PHP version, mitigation setting, proposed changes, and
   required checks. Approve only this displayed scope.
5. Follow the run. Success requires checks against the candidate and again at the
   original address. Clinics also upload an actual 3 MiB file and verify its hash.
6. Return to Fleet and open each site's run. The report distinguishes a model
   proposal from a previously verified recipe; both pass the same checks.

## Reset and repeat

Open **Demo controls**, optionally select **Also clear recipe memory**, and select
**Reset fleet**. Confirm the reset. It restores the vulnerable local baseline and
retains historical reports. Current site cards must stop claiming a patched state.
Clear recipes before demonstrating the first model proposal again.

Fault playback in **simulated demo data** is a separate UI demonstration. Do not
present it as a real rejected deployment. Real staging/restoration behavior is
covered by the Docker acceptance tests.

## Recorded acceptance

On 2026-10-24, browser-driven run
`run-77575165a53d49c9b6d4f3c622379696` completed with actual Anthropic proposals:

| Site | Plan source | Live checks | Observed PHP |
| --- | --- | --- | --- |
| pantry-a | MODEL | 7/7 | 8.3.36 |
| pantry-b | VERIFIED_RECIPE | 7/7 | 8.3.36 |
| clinic-a | MODEL | 9/9 | 8.3.36 |
| clinic-b | VERIFIED_RECIPE | 9/9 | 8.3.36 |

All four reported complete evidence and disabled upload-progress tracking. The run
contains 96 baseline, staging, and live checks, including 32 passing live checks.
Local evidence remains under `var/runs/<runId>/`; it is intentionally ignored by
Git. This is deployment acceptance, not a benchmark or a claim of broad security
coverage.

A reset restored all four 8.3.35 baselines, cleared recipes, and preserved that
report. A second browser-driven run,
`run-2568db06fb8a4e57b480718e42019301`, repeated the same verified outcomes and
recorded each site's provider provenance separately.

![Verified fleet in the desktop dashboard](fleet-verified.png)

[Mobile dashboard screenshot](fleet-mobile.png)

## Validation commands

```bash
DOCKER_CONTEXT=lima-patchpilot-demo uv run --locked --extra dev python -m pytest -q -p no:cacheprovider
node src/patchpilot/static/scripts/verify-api.mjs
node src/patchpilot/static/scripts/verify-mock.mjs
uv build
```

The complete Python gate passed **162 tests**, including the Docker tests, on
2026-10-24. The API contract and five mock scenarios passed separately. Real
Chrome checks covered desktop/mobile layouts, URL draft persistence, approval,
per-site reports, clean console output, and successful asset responses. The
browser/provider rehearsals above are separate from the simulated scenarios.
