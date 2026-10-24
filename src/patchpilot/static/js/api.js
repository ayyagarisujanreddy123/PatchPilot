/** All network I/O and explicit mock/live selection. */
import { createMockApi } from "./mock.js";
import { isMockRequestedInUrl } from "./util.js";
import { getUi, patchUi } from "./state.js";
import { normalizeSite, normalizeRun, normalizeEvent } from "./live.js";
import { validateWebsiteReport } from "./website.js";
import { validateRepositoryConnection, validateRepositoryRepair } from "./repositoryRepairModel.js";

let mockApi;
let liveForced = false;
let csrfToken = null;
let sessionPromise = null;
let liveHealth = null;
let knownRuns = [];
const assessments = new Map();
const latestRuns = new Map();
const currentRunIds = new Map();
const eventCursors = new Map();
const pendingApprovals = new Map();

function resolveMockApi() {
    mockApi ??= createMockApi({ getUiSeedFault: () => getUi().seedFault });
    return mockApi;
}

export function isMockMode() {
    return !liveForced && (getUi().mockMode || isMockRequestedInUrl());
}

export function enableMockModeFromUi() {
    liveForced = false;
    patchUi({ mockMode: true, backendUnreachable: false, lastErrorMessage: null });
    resolveMockApi().activate(getUi().seedFault);
}

export function enableLiveMode() {
    liveForced = true;
    patchUi({ mockMode: false });
}

async function fetchJson(path, init = {}) {
    const response = await fetch(path, { credentials: "same-origin", ...init,
        headers: { "Content-Type": "application/json", ...init.headers } });
    const payload = response.status === 204 ? null : await response.json().catch(() => null);
    if (!response.ok) {
        const error = new Error(payload?.error?.message ?? `Request failed (HTTP ${response.status}).`);
        error.status = response.status;
        error.code = payload?.error?.code;
        error.details = payload?.error?.details;
        throw error;
    }
    return payload;
}

async function ensureSession() {
    if (csrfToken) { return; }
    sessionPromise ??= fetchJson("/api/session").then((session) => {
        if (!session?.csrfToken) { throw new Error("The backend did not establish an operator session."); }
        csrfToken = session.csrfToken;
    }).finally(() => { sessionPromise = null; });
    await sessionPromise;
}

async function mutate(path, body = {}, headers = {}) {
    await ensureSession();
    return fetchJson(path, { method: "POST", headers: { "X-CSRF-Token": csrfToken, ...headers }, body: JSON.stringify(body) });
}

// Public website assessments always use the real API, independently of lab mock mode.
export async function createWebsiteAssessment(url) {
    const result = await mutate("/api/website-assessments", { url });
    if (!result?.assessmentId) { throw new Error("The backend did not return a website assessment ID. Refresh assessment history before retrying."); }
    return result;
}

export async function getWebsiteAssessment(assessmentId) {
    await ensureSession();
    return validateWebsiteReport(await fetchJson(`/api/website-assessments/${encodeURIComponent(assessmentId)}`));
}

export async function getWebsiteAssessmentHistory() {
    await ensureSession();
    const result = await fetchJson("/api/website-assessments");
    if (!Array.isArray(result?.items)) { throw new Error("Invalid website assessment history response."); }
    return result.items.map(validateWebsiteReport);
}

export async function getWebsiteExamples() {
    await ensureSession();
    const result = await fetchJson("/api/website-assessments/examples");
    if (!Array.isArray(result?.items)) { throw new Error("Invalid public sample list response."); }
    return result.items;
}

// Connected repairs use the local operator's real GitHub account, never lab mocks.
export async function getRepositoryGitHubStatus() {
    await ensureSession();
    const result = await fetchJson("/api/repository-connections/status");
    if (typeof result?.available !== "boolean") { throw new Error("Invalid GitHub account status response."); }
    return result;
}

export async function getRepositoryConnections(assessmentId) {
    await ensureSession();
    const result = await fetchJson(`/api/repository-connections?assessmentId=${encodeURIComponent(assessmentId)}`);
    if (!Array.isArray(result?.items)) { throw new Error("Invalid repository connection history response."); }
    return result.items.map(validateRepositoryConnection);
}

export async function createRepositoryConnection(assessmentId, repositoryUrl, capabilities) {
    return validateRepositoryConnection(await mutate("/api/repository-connections", { assessmentId, repositoryUrl, capabilities }));
}

export async function createRepositoryRepair(connectionId) {
    const result = await mutate("/api/repository-repairs", { connectionId });
    if (!result?.repairId) { throw new Error("The backend did not return a repository repair ID. Refresh before retrying."); }
    return result;
}

export async function getRepositoryRepair(repairId) {
    await ensureSession();
    return validateRepositoryRepair(await fetchJson(`/api/repository-repairs/${encodeURIComponent(repairId)}`));
}

export async function getRepositoryRepairs(assessmentId) {
    await ensureSession();
    const result = await fetchJson(`/api/repository-repairs?assessmentId=${encodeURIComponent(assessmentId)}`);
    if (!Array.isArray(result?.items)) { throw new Error("Invalid repository repair history response."); }
    return result.items.map(validateRepositoryRepair);
}

export async function publishRepositoryRepair(repairId, idempotencyKey) {
    if (!idempotencyKey) { throw new Error("A stable publication request key is required."); }
    const result = await mutate(`/api/repository-repairs/${encodeURIComponent(repairId)}/pull-request`, {}, { "Idempotency-Key": idempotencyKey });
    if (result?.repairId !== repairId) { throw new Error("The backend did not identify this publication. Refresh the repair before retrying."); }
    return result;
}

async function listRuns() {
    const runs = [];
    let cursor = null;
    const seen = new Set();
    do {
        const page = await fetchJson(`/api/runs?limit=100${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ""}`);
        if (!Array.isArray(page?.items)) { throw new Error("Invalid run-history response."); }
        runs.push(...page.items);
        cursor = page.nextCursor;
        if (cursor && seen.has(cursor)) { throw new Error("Run-history pagination did not advance."); }
        seen.add(cursor);
    } while (cursor);
    return runs;
}

export async function getState() {
    if (isMockMode()) {
        const data = await resolveMockApi().getState();
        return { ...data, health: { mode: "MOCK", ready: true, prepared: true }, recipesAvailable: true };
    }
    const [health, fleet, history] = await Promise.all([
        fetchJson("/api/health"), fetchJson("/api/sites"), listRuns(),
    ]);
    if (!Array.isArray(fleet?.items)) { throw new Error("Invalid registered-fleet response."); }
    if (!["REAL", "SIMULATION"].includes(health?.mode)) { throw new Error("The backend did not identify its execution mode."); }
    liveHealth = health;
    knownRuns = history;
    latestRuns.clear();
    currentRunIds.clear();
    const ordered = [...history].sort((a, b) => String(b.startedAt ?? b.createdAt ?? "").localeCompare(String(a.startedAt ?? a.createdAt ?? "")));
    for (const run of ordered) {
        for (const siteId of run.siteIds ?? []) {
            if (!latestRuns.has(siteId)) { latestRuns.set(siteId, run); }
        }
    }
    const byId = new Map(history.map((run) => [run.runId, run]));
    const sites = fleet.items.map((site) => {
        const active = ordered.find((run) => health.busy && !run.finishedAt && run.siteIds?.includes(site.siteId)
            && (!health.activeOperation?.id || health.activeOperation.id === run.runId));
        const current = active ?? (site.lastRunId ? byId.get(site.lastRunId) : null);
        // Historical runs remain reviewable, but a reset clears current patch status.
        if (current) { latestRuns.set(site.siteId, current); currentRunIds.set(site.siteId, current.runId); }
        return normalizeSite(site, current, assessments.get(site.siteId));
    });
    return { busy: Boolean(health.busy), health, sites, advisory: null, metrics: null,
        recipes: [], recipesAvailable: false };
}

export async function getRun(siteId) {
    if (isMockMode()) { return resolveMockApi().getRun(siteId); }
    const runId = latestRuns.get(siteId)?.runId;
    if (!runId) { return null; }
    const [record, report] = await Promise.all([
        fetchJson(`/api/runs/${encodeURIComponent(runId)}`),
        fetchJson(`/api/runs/${encodeURIComponent(runId)}/report`),
    ]);
    latestRuns.set(siteId, record);
    return { ...normalizeRun(record, report, siteId), historical: currentRunIds.get(siteId) !== runId };
}

export async function getEvents(since) {
    if (isMockMode()) { return resolveMockApi().getEvents(since); }
    if (since === 0) { eventCursors.clear(); }
    const events = [];
    const nextCursors = new Map(eventCursors);
    for (const run of knownRuns) {
        let after = eventCursors.get(run.runId) ?? 0;
        while (true) {
            const page = await fetchJson(`/api/runs/${encodeURIComponent(run.runId)}/events?after=${after}&limit=100`);
            if (!Array.isArray(page?.items)) { throw new Error("Invalid run-event response."); }
            events.push(...page.items.map((event) => normalizeEvent(event, run.runId)));
            const next = page.nextSequence ?? after;
            nextCursors.set(run.runId, next);
            if (page.items.length < 100 || next <= after) { break; }
            after = next;
        }
    }
    for (const [runId, sequence] of nextCursors) { eventCursors.set(runId, sequence); }
    return events.sort((a, b) => String(a.ts).localeCompare(String(b.ts)) || a.sequence - b.sequence);
}

export async function getPlanPreview(scope) {
    const siteIds = Array.isArray(scope) ? scope : [scope];
    if (isMockMode()) { return resolveMockApi().getPlanPreview(siteIds[0]); }
    const items = [];
    // The backend locks assessments; inspect this explicit scope sequentially.
    for (const siteId of siteIds) {
        const item = await mutate("/api/assessments", { siteId });
        if (item?.siteId !== siteId || !item.assessmentId || !item.fingerprint || !item.policyRevision) {
            throw new Error("The assessment did not identify the requested registered site.");
        }
        assessments.set(siteId, item);
        items.push(item);
    }
    const policyRevision = items[0]?.policyRevision;
    if (items.some((item) => item.policyRevision !== policyRevision)) {
        throw new Error("The security policy changed during assessment. Review the scope again.");
    }
    return { live: true, siteIds, assessments: items, policyRevision,
        canRepair: items.every((item) => item.canRepair),
        simulation: liveHealth?.mode === "SIMULATION" };
}

export async function approveAndRepair(scope, { seedFault = false, plan } = {}) {
    const siteIds = Array.isArray(scope) ? scope : [scope];
    if (isMockMode()) {
        for (const siteId of siteIds) { await resolveMockApi().postApprove({ site_id: siteId }); }
        return resolveMockApi().postRepair({ site_ids: siteIds, seed_fault: seedFault });
    }
    if (!plan?.live || !plan.canRepair || JSON.stringify(plan.siteIds) !== JSON.stringify(siteIds)) {
        throw new Error("Review a fresh assessment for this exact site scope before approving.");
    }
    const scopeKey = JSON.stringify(plan.assessments.map((item) => [item.assessmentId, item.fingerprint]));
    let pending = pendingApprovals.get(scopeKey);
    if (!pending) {
        const approval = await mutate("/api/approvals", {
            assessments: plan.assessments.map(({ assessmentId, fingerprint }) => ({ assessmentId, fingerprint })),
            policyRevision: plan.policyRevision,
        });
        if (!approval?.approvalId || JSON.stringify([...(approval.siteIds ?? [])].sort()) !== JSON.stringify([...siteIds].sort())) {
            throw new Error("The backend approved a different site scope. Repair was not submitted.");
        }
        pending = { approval, key: crypto.randomUUID() };
        pendingApprovals.set(scopeKey, pending);
    }
    const result = await mutate("/api/runs", { approvalId: pending.approval.approvalId, memoryEnabled: true }, { "Idempotency-Key": pending.key });
    if (!result?.runId) { throw new Error("The backend did not return a repair run ID."); }
    return result;
}

export async function postReset({ clear_memory = false } = {}) {
    if (isMockMode()) { return resolveMockApi().postReset({ clear_memory }); }
    const result = await mutate("/api/resets", { clearRecipes: Boolean(clear_memory) }, { "Idempotency-Key": crypto.randomUUID() });
    assessments.clear();
    if (!result?.resetId) { throw new Error("The backend did not return a reset operation ID."); }
    const deadline = Date.now() + 300000;
    while (Date.now() < deadline) {
        const reset = await fetchJson(`/api/resets/${encodeURIComponent(result.resetId)}`);
        if (reset.state === "COMPLETED") { return reset; }
        if (reset.state === "FAILED") { throw new Error(reset.error ?? reset.message ?? "Fixture reset failed. Review the backend operation."); }
        await new Promise((resolve) => setTimeout(resolve, 1000));
    }
    throw new Error("Reset is still pending. Check the backend operation before trying again.");
}

export async function postPrepare() {
    if (isMockMode()) { return null; }
    const result = await mutate("/api/prepare", {}, { "Idempotency-Key": crypto.randomUUID() });
    assessments.clear();
    return result;
}

export function initApiFromUrl() {
    if (isMockRequestedInUrl()) {
        patchUi({ mockMode: true });
        resolveMockApi().activate(getUi().seedFault);
    }
}

export function disposeMockTimers() { mockApi?.dispose?.(); }
