/** Repository repair orchestration; no idle timers and no automatic mutations. */
import { getState, patchState, patchUi } from "./state.js";
import { getRepositoryGitHubStatus, getRepositoryConnections, getRepositoryRepairs, getRepositoryRepair,
    createRepositoryConnection, createRepositoryRepair, publishRepositoryRepair } from "./api.js";
import { REPOSITORY_ACTIVE_STATES, hasPublishableProof, validateRepositoryUrl } from "./repositoryRepairModel.js";

const requests = new Map();
const publicationKeys = new Map();
let pollTimer = null;

function dataFor(id) { return getState().repositoryRepairs[id] ?? {}; }
function update(id, partial) {
    const previous = dataFor(id);
    const value = { ...previous, ...partial };
    if (JSON.stringify(previous) !== JSON.stringify(value)) {
        patchState({ repositoryRepairs: { ...getState().repositoryRepairs, [id]: value } });
    }
}
function selected(id) { return getState().ui.route === "scan" && getState().ui.selectedAssessmentId === id; }
function latest(items) { return [...items].sort((a, b) => String(b.createdAt).localeCompare(String(a.createdAt)))[0] ?? null; }
function focusAfterRender(id, target) {
    globalThis.requestAnimationFrame?.(() => { if (selected(id)) { document.getElementById(target)?.focus({ preventScroll: true }); } });
}

export function publicationKey(repairId, create = false) {
    const storageKey = `patchpilot.repository-publication.${repairId}`;
    let key = publicationKeys.get(repairId);
    try { key ??= sessionStorage.getItem(storageKey); } catch { /* Memory preserves retries if storage is unavailable. */ }
    if (!key && create) { key = crypto.randomUUID(); }
    if (key) {
        publicationKeys.set(repairId, key);
        try { sessionStorage.setItem(storageKey, key); } catch { /* Keep the in-memory key. */ }
    }
    return key;
}

export function canRetryPublication(report) {
    return report?.state === "FAILED" && Boolean(report.patch && publicationKey(report.repairId))
        && report.events.some((event) => event.state === "PUBLISHING");
}

export function stopRepositoryRepairPolling() {
    if (pollTimer) { clearTimeout(pollTimer); pollTimer = null; }
}

function schedule(id) {
    if (!selected(id)) { return; }
    stopRepositoryRepairPolling();
    if (REPOSITORY_ACTIVE_STATES.has(dataFor(id).report?.state)) {
        pollTimer = setTimeout(() => refreshRepositoryRepairs(getState().websiteReports[id]), 1000);
    }
}

export async function refreshRepositoryRepairs(assessment, { force = false } = {}) {
    if (!assessment || assessment.state !== "COMPLETED") {
        stopRepositoryRepairPolling(); return;
    }
    if (!selected(assessment.assessmentId)) { return; }
    const id = assessment.assessmentId;
    if (requests.has(id)) { return requests.get(id); }
    const previous = dataFor(id);
    if (previous.loaded && !force && !REPOSITORY_ACTIVE_STATES.has(previous.report?.state)) { return; }
    if (!previous.loaded) { update(id, { loading: true }); }
    const request = (async () => {
        try {
            if (!previous.loaded || force) {
                const [status, connections, reports] = await Promise.all([getRepositoryGitHubStatus(), getRepositoryConnections(id), getRepositoryRepairs(id)]);
                if (JSON.stringify(status) !== JSON.stringify(getState().repositoryGitHubStatus)) { patchState({ repositoryGitHubStatus: status }); }
                const connection = latest(connections.filter((item) => item.assessmentId === id));
                const report = latest(reports.filter((item) => item.assessmentId === id && item.connectionId === connection?.connectionId));
                update(id, { loaded: true, loading: false, fetchError: null, connections, connection, report });
            } else {
                const report = await getRepositoryRepair(previous.report.repairId);
                update(id, { report, fetchError: null });
            }
        } catch (error) { update(id, { loading: false, fetchError: error.message }); }
        finally { schedule(id); }
    })().finally(() => requests.delete(id));
    requests.set(id, request);
    return request;
}

async function action(id, kind, work) {
    if (dataFor(id).busyAction) { return; }
    update(id, { busyAction: kind, actionError: null });
    try { await work(); }
    catch (error) { update(id, { actionError: error.message }); focusAfterRender(id, "repository-repair-error"); }
    finally { update(id, { busyAction: null }); }
}

export const repositoryRepairHandlers = {
    onDraft: (id, partial) => {
        const drafts = getState().ui.repositoryDrafts;
        patchUi({ repositoryDrafts: { ...drafts, [id]: { ...drafts[id], ...partial } } }, { render: false });
    },
    onRefresh: (id) => refreshRepositoryRepairs(getState().websiteReports[id], { force: true }),
    onConnect: (id) => action(id, "connect", async () => {
        const draft = getState().ui.repositoryDrafts[id] ?? {};
        let repositoryUrl;
        try { repositoryUrl = validateRepositoryUrl(draft.url ?? ""); }
        catch (error) {
            update(id, { actionError: error.message });
            focusAfterRender(id, "repository-url");
            return;
        }
        const capabilities = ["homepage", ...(draft.contact !== false ? ["contact"] : []), ...(draft.upload !== false ? ["upload"] : [])];
        const connection = await createRepositoryConnection(id, repositoryUrl, capabilities);
        if (connection.assessmentId !== id) { throw new Error("The connection belongs to a different assessment. No repair was started."); }
        update(id, { connection, connections: [connection, ...(dataFor(id).connections ?? [])], report: null, fetchError: null });
        focusAfterRender(id, "repository-prepare");
    }),
    onPrepare: (connection) => action(connection.assessmentId, "prepare", async () => {
        const result = await createRepositoryRepair(connection.connectionId);
        const report = await getRepositoryRepair(result.repairId);
        if (report.connectionId !== connection.connectionId) { throw new Error("The backend returned a repair for a different repository connection."); }
        update(connection.assessmentId, { report, fetchError: null });
        focusAfterRender(connection.assessmentId, "repository-repair-heading");
        schedule(connection.assessmentId);
    }),
    onPublish: (report) => action(report.assessmentId, "publish", async () => {
        if (!hasPublishableProof(report) && !canRetryPublication(report)) { throw new Error("Complete candidate verification before creating a draft pull request."); }
        const key = publicationKey(report.repairId, true);
        try { await publishRepositoryRepair(report.repairId, key); }
        finally {
            // A lost response may still have created the PR. Refresh without submitting again.
            try { update(report.assessmentId, { report: await getRepositoryRepair(report.repairId), fetchError: null }); }
            catch (error) { update(report.assessmentId, { fetchError: error.message }); }
            schedule(report.assessmentId);
            focusAfterRender(report.assessmentId, dataFor(report.assessmentId).report?.state === "PUBLISHED" ? "repository-pr-link" : "repository-repair-heading");
        }
    }),
};
