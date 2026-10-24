/** Resource API contract checks with a local fetch double; never contacts a server. */
import assert from "node:assert/strict";
import { webcrypto } from "node:crypto";
import { matchRegisteredUrl, normalizeSite, normalizeRun, groupChecks } from "../js/live.js";

// Set browser globals before choosing the live adapter.
globalThis.window = { location: { search: "" } };
globalThis.crypto ??= webcrypto;
const api = await import("../js/api.js");
api.enableLiveMode();
const calls = [];
let active = false;
let failRunOnce = true;
let approvedSites = ["pantry-a", "clinic-a"];
let lastRunIds = { "pantry-a": null, "clinic-a": null };
const sites = [
    { siteId: "pantry-a", displayName: "Pantry", baseUrl: "http://127.0.0.1:8081", capabilities: ["homepage", "contact"] },
    { siteId: "clinic-a", displayName: "Clinic", baseUrl: "http://127.0.0.1:8083", capabilities: ["homepage", "contact", "upload"] },
];
const oldRun = { runId: "run-old", siteIds: ["pantry-a"], currentSiteId: "pantry-a", state: "VERIFIED", startedAt: "2026-10-24T10:00:00Z", finishedAt: "2026-10-24T10:01:00Z", checks: [], planSource: "MODEL" };
const liveRun = { runId: "run-new", siteIds: ["pantry-a", "clinic-a"], currentSiteId: "clinic-a", state: "STAGING", startedAt: "2026-10-24T11:00:00Z", finishedAt: null, planSource: "MODEL", checks: [], siteResults: { "pantry-a": { state: "VERIFIED", planSource: "VERIFIED_RECIPE", final: { php_version: "8.3.36", sapi: "apache2handler" }, checks: [
    { checkId: "upload", siteId: "pantry-a", phase: "STAGING", passed: false },
    { checkId: "homepage", siteId: "pantry-a", phase: "LIVE", passed: true },
] } } };
function response(body, status = 200) { return { status, ok: status >= 200 && status < 300, json: async () => body }; }
globalThis.fetch = async (path, init = {}) => {
    const body = init.body ? JSON.parse(init.body) : null;
    calls.push({ path, ...init, body });
    assert.ok(path.startsWith("/api/"), "only relative resource API calls are allowed");
    assert.equal(init.credentials, "same-origin");
    if (init.method === "POST") { assert.equal(init.headers["X-CSRF-Token"], "csrf-test"); }
    if (path === "/api/session") { return response({ csrfToken: "csrf-test" }); }
    if (path === "/api/health") { return response({ mode: "REAL", ready: true, prepared: true, busy: active, activeOperation: active ? { kind: "run", id: "run-new" } : null }); }
    if (path === "/api/sites") { return response({ items: sites.map((site) => ({ ...site, assessmentState: "UNASSESSED", lastRunId: lastRunIds[site.siteId] })), nextCursor: null }); }
    if (path === "/api/runs?limit=100") { return response({ items: active ? [liveRun] : [], nextCursor: "page-two" }); }
    if (path === "/api/runs?limit=100&cursor=page-two") { return response({ items: [oldRun], nextCursor: null }); }
    if (path === "/api/assessments") { return response({ assessmentId: `ass-${body.siteId}`, siteId: body.siteId, fingerprint: `fp-${body.siteId}`, policyRevision: "policy-v1", canRepair: true, currentRuntime: { phpVersion: "8.3.34", sapi: "apache2handler" }, requiredChecks: ["serving_runtime", "homepage", "contact"], proposedChanges: ["Approved fixed image"] }); }
    if (path === "/api/approvals") {
        assert.deepEqual(body, { assessments: [{ assessmentId: "ass-pantry-a", fingerprint: "fp-pantry-a" }, { assessmentId: "ass-clinic-a", fingerprint: "fp-clinic-a" }], policyRevision: "policy-v1" });
        return response({ approvalId: "approval-scope", siteIds: approvedSites });
    }
    if (path === "/api/runs" && init.method === "POST") {
        assert.deepEqual(body, { approvalId: "approval-scope", memoryEnabled: true });
        assert.ok(init.headers["Idempotency-Key"]);
        if (failRunOnce) { failRunOnce = false; throw new Error("Synthetic lost response"); }
        return response({ runId: "run-new", statusUrl: "/api/runs/run-new" }, 202);
    }
    if (path === "/api/runs/run-new") { return response(liveRun); }
    if (path === "/api/runs/run-old") { return response(oldRun); }
    if (path.endsWith("/report")) { return response({ checks: [], changes: [], securityResults: null, recovery: null, provenance: { source: "MODEL" }, warnings: [] }); }
    if (path.includes("/events?")) {
        const after = Number(new URL(path, "http://local").searchParams.get("after"));
        return response({ items: after ? [] : [{ sequence: 1, siteId: "pantry-a", timestamp: "2026-10-24T11:00:00Z", state: "STAGING", message: "Actual recorded event" }], nextSequence: 1 });
    }
    if (path === "/api/resets") { assert.deepEqual(body, { clearRecipes: true }); lastRunIds = { "pantry-a": null, "clinic-a": null }; return response({ resetId: "reset-one" }, 202); }
    if (path === "/api/resets/reset-one") { return response({ resetId: "reset-one", state: "COMPLETED" }); }
    if (path === "/api/prepare") { return response({ state: "COMPLETED", sites: [], imageDigest: "sha256:actual" }); }
    throw new Error(`Unexpected API call: ${path}`);
};

let state = await api.getState();
assert.equal(state.sites[0].status, "unassessed", "historical VERIFIED must not override cleared lastRunId");
assert.equal(state.metrics, null);
assert.equal(state.recipesAvailable, false);
assert.equal((await api.getRun("pantry-a")).historical, true);
const scope = ["pantry-a", "clinic-a"];
const plan = await api.getPlanPreview(scope);
assert.equal(plan.assessments.length, 2);
await assert.rejects(api.approveAndRepair(["clinic-a"], { plan }), /exact site scope/);
await assert.rejects(api.approveAndRepair(scope, { plan }), /Synthetic lost response/);
assert.equal((await api.approveAndRepair(scope, { plan })).runId, "run-new");
const submissions = calls.filter((call) => call.path === "/api/runs" && call.method === "POST");
assert.equal(submissions.length, 2);
assert.equal(submissions[0].headers["Idempotency-Key"], submissions[1].headers["Idempotency-Key"], "retry must retain the submission key");
assert.equal(calls.filter((call) => call.path === "/api/approvals").length, 1, "retry must retain approval ID");
active = true;
state = await api.getState();
assert.equal(state.sites[0].status, "patched_verified", "completed fleet member has its own result");
assert.equal(state.sites[1].status, "staging");
assert.equal(state.sites[0].php_version, "8.3.36");
assert.equal(state.sites[0].checks_passed, 1);
assert.equal(state.sites[0].checks_required, 1, "historical staging failures do not count as current LIVE checks");
const events = await api.getEvents(0);
assert.equal(events.length, 2, "events from separate runs retain distinct IDs");
assert.notEqual(events[0].id, events[1].id);
assert.equal((await api.getEvents(events.at(-1).id)).length, 0);
assert.equal((await api.getRun("pantry-a")).outcome, "patched_verified");
assert.equal((await api.getRun("pantry-a")).plan_source, "VERIFIED_RECIPE");
assert.equal((await api.getRun("pantry-a")).provenance.source, "VERIFIED_RECIPE");
assert.ok(!(await api.getRun("pantry-a")).provenance.modelId, "other fleet members' provider details must not leak into this site's provenance");
assert.equal((await api.getRun("clinic-a")).outcome, null);
active = false;
await api.postReset({ clear_memory: true });
state = await api.getState();
assert.equal(state.sites[0].status, "unassessed");
await api.postPrepare();
const visibleSites = sites.map((site) => ({ id: site.siteId, address: site.baseUrl }));
assert.equal(matchRegisteredUrl("http://127.0.0.1:8081/", visibleSites), "pantry-a");
for (const url of ["https://example.org", "http://example.org", "http://127.0.0.1:9999", "http://127.0.0.1:8081/private", "http://user@127.0.0.1:8081", "http://127.0.0.1:8081/?scope=all"]) {
    assert.throws(() => matchRegisteredUrl(url, visibleSites));
}
assert.equal(normalizeRun({ ...oldRun, planSource: "TEST_DOUBLE" }).simulation, true);
assert.equal(normalizeSite(sites[0]).status, "unassessed");
const grouped = groupChecks(liveRun.siteResults["pantry-a"].checks);
assert.equal(grouped.phase, "LIVE");
assert.equal(grouped.current.length, 1);
assert.equal(grouped.failures.length, 1, "earlier staging failures remain visible alongside final evidence");
console.log("PASS: resource API routes, CSRF, exact approval scope, retry idempotency, pagination, per-site fleet state, reset freshness, event cursors, registered URL boundary, and simulation labeling");
