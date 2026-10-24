/**
 * All network I/O. Swap mock vs live backend only in this module.
 */

import { createMockApi } from "./mock.js";
import { isMockRequestedInUrl } from "./util.js";
import { getUi, patchUi } from "./state.js";

const JSON_HEADERS = { "Content-Type": "application/json" };

let mockApi = null;
let liveForced = false;

function resolveMockApi() {
    if (!mockApi) {
        mockApi = createMockApi({
            getUiSeedFault: () => getUi().seedFault,
        });
    }
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

async function fetchJson(path, init) {
    const response = await fetch(path, {
        ...init,
        headers: { ...JSON_HEADERS, ...init?.headers },
    });
    if (!response.ok) {
        const text = await response.text();
        throw new Error(text || `HTTP ${response.status}`);
    }
    if (response.status === 204) {
        return null;
    }
    return response.json();
}

export async function getState() {
    if (isMockMode()) {
        return resolveMockApi().getState();
    }
    return fetchJson("/api/state");
}

export async function getRun(siteId) {
    if (isMockMode()) {
        return resolveMockApi().getRun(siteId);
    }
    return fetchJson(`/api/sites/${encodeURIComponent(siteId)}/run`);
}

export async function getEvents(since) {
    if (isMockMode()) {
        return resolveMockApi().getEvents(since);
    }
    const q = since != null ? `?since=${encodeURIComponent(String(since))}` : "";
    return fetchJson(`/api/events${q}`);
}

// UI calls POST /api/approve then POST /api/repair for the approved site_id (confirm with backend).
export async function approveAndRepair(siteId, { seedFault = false } = {}) {
    await postApprove({ site_id: siteId });
    return postRepair({ site_ids: [siteId], seed_fault: seedFault });
}

export async function postRepair(body) {
    if (isMockMode()) {
        return resolveMockApi().postRepair(body);
    }
    return fetchJson("/api/repair", { method: "POST", body: JSON.stringify(body) });
}

export async function postApprove(body) {
    if (isMockMode()) {
        return resolveMockApi().postApprove(body);
    }
    return fetchJson("/api/approve", { method: "POST", body: JSON.stringify(body) });
}

export async function getPlanPreview(siteId) {
    if (isMockMode()) {
        return resolveMockApi().getPlanPreview(siteId);
    }
    try {
        return await fetchJson(`/api/sites/${encodeURIComponent(siteId)}/plan-preview`);
    } catch {
        return null;
    }
}

export async function postReset(body) {
    if (isMockMode()) {
        return resolveMockApi().postReset(body);
    }
    return fetchJson("/api/reset", { method: "POST", body: JSON.stringify(body) });
}

export function initApiFromUrl() {
    if (isMockRequestedInUrl()) {
        patchUi({ mockMode: true });
        resolveMockApi().activate(getUi().seedFault);
    }
}

export function disposeMockTimers() {
    mockApi?.dispose?.();
}
