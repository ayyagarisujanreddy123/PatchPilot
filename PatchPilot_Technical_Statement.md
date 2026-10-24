# PatchPilot Technical Statement

*Architecture and prototype specification*

Product concept  |  24 October 2026

**Technical objective:** convert an approved security advisory into a constrained, testable deployment, preserve required application behavior, and retain verified repair knowledge for compatible future deployments. This statement defines the proposed system and its initial hackathon acceptance criteria.

## Authorized connection and autonomy

PatchPilot requires an authorized connection to the environment being maintained. A public website address alone does not supply permission or the access needed to replace a runtime. Production support would use a scoped hosting integration or an owner-installed service.

An owner approves a repair plan or a maintenance policy specifying eligible systems, permitted changes, activation conditions, and escalation rules. The controller operates within that authority. Credentials and deployment permissions remain outside the model; unsupported environments or uncertain findings are escalated.

## System responsibilities

| **Component** | **Responsibility** |
| --- | --- |
| Assessment | Match observed runtime and configuration to an approved advisory. |
| Planner | Propose a typed repair and revise it using failed-test evidence. |
| Controller | Enforce policy, bounded operations, attempts, and activation gates. |
| Verifier | Run unchanged runtime and application checks; record evidence. |
| Playbook store | Retain successful recipes and their compatibility requirements. |
| Dashboard | Present actual status, provenance, outcomes, and exceptions. |

## Initial security policy

For the controlled PHP 8.3 fixtures, the approved fixed release is 8.3.36 for CVE-2026-109618 and CVE-2026-109619. Vendor packages require package-specific rules because fixes may be backported. [1]

The October 23 PHP notice describes an additional conditional issue, CVE-2026-115560. The prototype will retain `session.upload_progress.enabled=0` in every candidate as a conservative policy. The success record identifies the original fixes and this mitigation separately. [2]

## The repair workflow

1. **Inspect and establish a baseline.** Capture the original deployment identity, launch settings, HTTP-serving runtime, and functional results. Record existing failures before making changes.

2. **Choose a compatible plan.** Use an exactly matching verified recipe or ask the model for a typed plan. Permit only approved images and configuration profiles.

3. **Validate and stage.** Reject unauthorized targets or settings. Create an isolated candidate with immutable application and configuration content. Wait for readiness within a deadline.

4. **Verify the candidate.** Run the required security and application checks. The model cannot modify the rules, weaken assertions, or declare success.

5. **Reject or revise.** A failing staging candidate is discarded while the original remains serving. Return the failure evidence to the planner and allow one revised candidate.

6. **Activate and recheck.** Activate the same image, application content, and configuration that passed staging. Repeat checks at the original address.

7. **Restore when required.** If activation or live checks fail, attempt restoration of the retained original and verify it. Report restoration failure explicitly. A restored old runtime is not marked patched.

8. **Commit the evidence.** Save the recipe only after final verification. Remove staging resources on every terminal outcome and preserve the run record.

## Verification contract

| **Check** | **Required evidence** |
| --- | --- |
| Serving runtime | Actual HTTP PHP version, SAPI, mitigation values, and deployment identity. [3] |
| Homepage and contact | Expected organization content; valid submission accepted and invalid input rejected. |
| Upload capability | A real 3 MiB multipart upload with the expected byte count and content hash. |
| Activation | The same checks pass again at the original site address. |

**Recovery boundary:** rejecting staging is different from rolling back a live deployment. Restoring a container does not reverse database or external-service changes. The initial fixtures use isolated, temporary state; a stop/start handoff may briefly interrupt service.

## Verified operational memory

The learning mechanism is reuse of validated repair knowledge. A recipe records the successful settings, failure observations, originating site and run, deployment identity, test results, and verification time. It is committed after activation passes, and it supplies a candidate for a later site.

An exact compatibility key includes the advisory revision, target image, runtime branch, server mode, application template revision, required capabilities, relevant starting configuration, and test-suite revision. Organization names and instance IDs are excluded. A material change invalidates the match; every reused recipe is tested again.

## Planner and execution boundaries

The model receives the approved policy, observed configuration, application requirements, and failure evidence. It returns an approved target-image alias, validated configuration profile, and a short rationale. Ordinary code resolves the target and performs fixed operations using argument arrays or a Docker API.

The model cannot issue arbitrary shell commands, select unregistered sites, change tests, or weaken a security requirement. The controller bounds attempts and waiting time. Cached or deterministic fallbacks are labeled by their actual source. If Strands is used, its typed structured output fits the plan contract. [5]

## Evidence and evaluation

| **Metric** | **Interpretation** |
| --- | --- |
| Plan source and recipe hits | Fresh planning, verified reuse, or an explicitly labeled fallback. |
| Planner invocations | Planning work performed; model requests are counted separately if instrumented. |
| Attempts and test results | Actual first-attempt outcome and passed/required checks. |
| Rejections and rollbacks | Separate counts for staging failures and restoration after activation. |
| Phase durations | Planning, staging, testing, activation, and total time measured separately. |

The memory comparison starts from equivalent original fleets, uses identical tests and pre-pulled images, and runs sequentially. Memory is disabled across sites in one arm and starts empty in the other. Each site receives a fresh model conversation when planning is needed. Include failures in the results.

Deliberately injected compatibility faults belong in a separate recovery demonstration. Observed reuse can establish reduced planning work; this small comparison does not establish a universal speedup or a steadily declining repair time.

## Proposed hackathon implementation

Use four real local Docker sites on one Apache/PHP branch: two basic homepage/contact fixtures and two with an upload requirement. One FastAPI process serves the API and dashboard, and one background worker repairs sites sequentially. A manifest defines allowed targets and images; JSON files and an append-only event log hold recipes and evidence.

A shared busy lock prevents a run and reset from overlapping. Reset restores only the project fleet, clears memory when requested, and retains completed run records. All targets and controls remain local to the demo laptop.

## Compatibility demonstration

The original upload fixture accepts a benign 3 MiB file with an 8M upload limit and 10M POST limit. A separately labeled seeded candidate uses a 2 MiB upload limit and fails the actual HTTP test. The revised candidate preserves the required upload settings while retaining the security mitigation. PHP documents the upload limit and the requirement for a larger POST limit. [4]

## Acceptance gates

| **Gate** | **Evidence required** |
| --- | --- |
| First working slice | A real runtime upgrade passes live checks within the first 75 minutes. |
| Compatibility recovery | A bad candidate is rejected; the revised candidate passes unchanged tests. |
| Fleet and reuse | Four sites complete through the dashboard; a matching recipe is reused and rechecked. |
| Deployment recovery | An activation failure restores the original and reports its state accurately. |
| Demo readiness | Two complete run/reset rehearsals and a usable recording before submission. |

Supported hosting connections, ongoing monitoring, stateful application recovery, and broad software coverage are product development work beyond this initial build. No-cost access is the mission; infrastructure and support require a sustainable operating model.

### Technical sources

[1] [CERT-EU advisory 2026-018](https://cert.europa.eu/publications/security-advisories/2026-018/)

[2] [PHP security announcements](https://www.php.net/index.php)

[3] [PHP manual on the serving interface](https://www.php.net/manual/en/function.php-sapi-name.php)

[4] [PHP upload configuration reference](https://www.php.net/manual/en/ini.core.php)

[5] [Strands structured output](https://strandsagents.com/docs/user-guide/sdk/agents/structured-output/)

Sources reviewed 24 October 2026. Architecture and acceptance gates are proposed specifications, not measured implementation results.
