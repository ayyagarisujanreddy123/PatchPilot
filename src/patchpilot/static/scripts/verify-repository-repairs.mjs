/** Contract and owner-action checks with intercepted transport. No real requests. */
import assert from "node:assert/strict";
import { validateRepositoryUrl, validateRepositoryRepair, hasPublishableProof, safePullRequestUrl } from "../js/repositoryRepairModel.js";
import { getState, patchState, patchUi, subscribe } from "../js/state.js";

assert.equal(validateRepositoryUrl(" https://github.com/owner/site.git "), "https://github.com/owner/site");
for (const value of ["http://github.com/owner/site", "https://github.com/owner/site/tree/main", "https://user:token@github.com/owner/site", "https://github.com/owner/site?token=x", "https://evil.example/owner/site", "javascript:alert(1)"]) {
    assert.throws(() => validateRepositoryUrl(value));
}
assert.throws(() => validateRepositoryRepair({ state: "READY_TO_PUBLISH" }), /incomplete/);
const assessmentId = "website-contract";
const connection = { connectionId: "connection-contract", assessmentId, repository: "owner/site", repositoryUrl: "https://github.com/owner/site", baseCommit: "a".repeat(40), defaultBranch: "main", createdAt: "2026-10-24T12:00:00Z", capabilities: ["homepage", "contact", "upload"], manifest: { siteId: "site-identity" } };
const report = { repairId: "repair-contract", connectionId: connection.connectionId, assessmentId, repository: "owner/site", baseCommit: connection.baseCommit, state: "READY_TO_PUBLISH", createdAt: "2026-10-24T12:00:01Z", stageMessage: "Candidate checks passed", capabilities: connection.capabilities, checks: [{ checkId: "baseline-banner", phase: "BASELINE", label: "PHP banner hidden", passed: false }, { checkId: "candidate-banner", phase: "CANDIDATE", label: "PHP banner hidden", passed: true }], events: [], limitations: ["No deployment"], proposal: { modelId: "actual-model", providerMessageId: "provider-id", inputTokens: 12, outputTokens: 8 }, patch: { path: "php.ini", unifiedDiff: "-expose_php=On\n+expose_php=Off" } };
assert.ok(hasPublishableProof(report), "baseline security findings do not hide a genuinely ready candidate");
assert.equal(hasPublishableProof({ ...report, checks: [] }), false);
assert.equal(hasPublishableProof({ ...report, checks: [...report.checks, { phase: "CANDIDATE", passed: false }] }), false);
assert.equal(safePullRequestUrl({ ...report, pullRequest: { number: 4, url: "javascript:alert(1)" } }), null);
assert.equal(safePullRequestUrl({ ...report, pullRequest: { number: 4, url: "https://github.com/other/site/pull/4" } }), null);

globalThis.window = { location: { search: "?mock=1" } };
globalThis.document = { getElementById: () => null };
const storage = new Map();
globalThis.sessionStorage = { getItem: (key) => storage.get(key) ?? null, setItem: (key, value) => storage.set(key, value) };
const timers = new Map();
let nextTimer = 0;
globalThis.setTimeout = (callback) => { timers.set(++nextTimer, callback); return nextTimer; };
globalThis.clearTimeout = (id) => timers.delete(id);
let currentReport = null;
let publishAttempts = 0;
let sessionCalls = 0;
const calls = [];
let resolveOldRead;
let markOldReadStarted;
const oldReadStarted = new Promise((resolve) => { markOldReadStarted = resolve; });
globalThis.fetch = async (path, init) => {
    calls.push({ path, ...init });
    assert.ok(path.startsWith("/api/"), "only same-origin API transport is permitted");
    assert.equal(init.credentials, "same-origin");
    let body;
    if (path === "/api/session") { sessionCalls++; body = { csrfToken: "repository-csrf" }; }
    else if (path === "/api/repository-connections/status") { body = { available: true, login: "local-owner", message: "Local GitHub authentication available" }; }
    else if (path === `/api/repository-connections?assessmentId=${assessmentId}`) { body = { items: [], nextCursor: null }; }
    else if (path === `/api/repository-repairs?assessmentId=${assessmentId}`) { body = { items: [], nextCursor: null }; }
    else if (path === "/api/repository-connections" && init.method === "POST") {
        assert.deepEqual(JSON.parse(init.body), { assessmentId, repositoryUrl: "https://github.com/owner/site", capabilities: ["homepage", "contact", "upload"] }); body = connection;
    } else if (path === "/api/repository-repairs" && init.method === "POST") {
        assert.deepEqual(JSON.parse(init.body), { connectionId: connection.connectionId });
        currentReport = { ...report, state: "PLANNING", checks: [], proposal: null, patch: null };
        body = { repairId: report.repairId, statusUrl: `/api/repository-repairs/${report.repairId}` };
    } else if (path === `/api/repository-repairs/${report.repairId}/pull-request`) {
        publishAttempts++;
        assert.ok(init.headers["Idempotency-Key"]);
        if (publishAttempts === 1) {
            currentReport = { ...report, state: "FAILED", events: [{ sequence: 1, state: "PUBLISHING", timestamp: "2026-10-24T12:00:02Z", message: "Publication started" }] };
            throw new Error("Simulated response loss");
        }
        currentReport = { ...report, state: "PUBLISHED", pullRequest: { number: 4, url: "https://github.com/owner/site/pull/4", draft: true } };
        body = { repairId: report.repairId, statusUrl: `/api/repository-repairs/${report.repairId}` };
    } else if (path === "/api/repository-repairs/repair-old") {
        markOldReadStarted();
        body = await new Promise((resolve) => { resolveOldRead = resolve; });
    } else if (path === `/api/repository-repairs/${report.repairId}`) { body = currentReport; }
    else { throw new Error(`Unexpected request ${path}`); }
    if (init.method === "POST") { assert.equal(init.headers["X-CSRF-Token"], "repository-csrf"); }
    return { status: 200, ok: true, json: async () => body };
};
const { refreshRepositoryRepairs, repositoryRepairHandlers: handlers, canRetryPublication } = await import("../js/repositoryRepairs.js");
const assessment = { assessmentId, state: "COMPLETED" };
patchState({ websiteReports: { [assessmentId]: assessment } });
patchUi({ route: "scan", selectedAssessmentId: assessmentId });
await refreshRepositoryRepairs(assessment);
assert.equal(sessionCalls, 1);
assert.equal(calls.filter((call) => call.method === "POST").length, 0, "opening a report never connects, repairs, or publishes");
assert.equal(timers.size, 0, "no idle polling");
let renders = 0;
const unsubscribe = subscribe(() => renders++);
handlers.onDraft(assessmentId, { url: "https://github.com/owner/site" });
assert.equal(renders, 0, "typing does not redraw the dashboard");
unsubscribe();
await handlers.onConnect(assessmentId);
assert.equal(calls.filter((call) => call.path === "/api/repository-repairs" && call.method === "POST").length, 0, "connecting never starts preparation");
await handlers.onPrepare(connection);
assert.equal(getState().repositoryRepairs[assessmentId].report.state, "PLANNING");
assert.equal(timers.size, 1, "active work polls");
const oldAssessment = { assessmentId: "website-old", state: "COMPLETED" };
const oldReport = { ...report, assessmentId: oldAssessment.assessmentId, repairId: "repair-old", state: "PLANNING" };
patchState({ repositoryRepairs: { ...getState().repositoryRepairs, [oldAssessment.assessmentId]: { loaded: true, report: oldReport } } });
patchUi({ selectedAssessmentId: oldAssessment.assessmentId });
const oldRefresh = refreshRepositoryRepairs(oldAssessment);
await oldReadStarted;
patchUi({ selectedAssessmentId: assessmentId });
await refreshRepositoryRepairs(assessment);
assert.equal(timers.size, 1);
resolveOldRead({ ...oldReport, state: "READY_TO_PUBLISH" });
await oldRefresh;
assert.equal(timers.size, 1, "a delayed old selection must not cancel the selected active repair timer");
await refreshRepositoryRepairs(oldAssessment);
assert.equal(timers.size, 1, "a stale timer callback must not cancel the selected repair timer");
currentReport = report;
await refreshRepositoryRepairs(assessment);
assert.equal(timers.size, 0, "ready work stops polling");
await handlers.onPublish(report);
const failedPublication = getState().repositoryRepairs[assessmentId].report;
assert.ok(canRetryPublication(failedPublication));
await handlers.onPublish(failedPublication);
const published = getState().repositoryRepairs[assessmentId].report;
assert.equal(published.state, "PUBLISHED");
assert.equal(safePullRequestUrl(published), "https://github.com/owner/site/pull/4");
const publications = calls.filter((call) => call.path.endsWith("/pull-request"));
assert.equal(publications.length, 2);
assert.equal(publications[0].headers["Idempotency-Key"], publications[1].headers["Idempotency-Key"], "an explicit failed-publication retry reuses the original key");
assert.equal(timers.size, 0);
const before = publications.length;
await handlers.onPublish({ ...report, state: "REJECTED" });
assert.equal(calls.filter((call) => call.path.endsWith("/pull-request")).length, before, "a rejected candidate cannot publish");
console.log("PASS: repository URL/contract guards, actual APIs under lab mock query, session/CSRF, read-only initial load, separate connect/prepare/publish actions, draft typing, active-only polling, baseline findings, exact proof guard, safe PR link, and stable publication retry key.");
