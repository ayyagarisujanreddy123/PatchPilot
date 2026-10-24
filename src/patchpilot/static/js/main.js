/**
 * Bootstrap, routing, polling, and top-level render orchestration.
 */

import {
    appendEvents,
    getState,
    patchState,
    patchUi,
    replaceEvents,
    setRun,
    subscribe,
} from "./state.js";
import {
    approveAndRepair,
    disposeMockTimers,
    getEvents,
    getPlanPreview,
    getRun,
    getState as fetchAppState,
    initApiFromUrl,
    isMockMode,
    enableMockModeFromUi,
    postReset,
    postPrepare,
    createWebsiteAssessment,
    getWebsiteAssessment,
    getWebsiteAssessmentHistory,
    getWebsiteExamples,
} from "./api.js";
import { matchRegisteredUrl } from "./live.js";
import { validateWebsiteUrl, WEBSITE_ACTIVE_STATES } from "./website.js";
import { repositoryRepairHandlers, refreshRepositoryRepairs, stopRepositoryRepairPolling } from "./repositoryRepairs.js";
import {
    renderBackendBanner,
    renderHeader,
    renderNav,
} from "./views/shell.js";
import { renderFleet } from "./views/fleet.js";
import { bindApprovalEscape, renderApproval } from "./views/approval.js";
import { renderRun } from "./views/run.js";
import { renderMetrics } from "./views/metrics.js";
import { renderRecipes } from "./views/recipes.js";
import { afterRenderEvents, renderEvents, resetEventsScrollTracking } from "./views/events.js";
import { renderDemoControls } from "./views/demoControls.js";
import { renderWebsite } from "./views/website.js";
import { clearElement, el } from "./util.js";

const POLL_ACTIVE_MS = 1000;
const POLL_IDLE_MS = 4000;

let pollTimer = null;
let approvalEscapeUnbind = null;
let lastFocusedBeforeApproval = null;
let assessmentRequest = 0;
let websiteRefresh = null;

function restoreApprovalFocus() {
    const previous = lastFocusedBeforeApproval;
    (previous?.id ? document.getElementById(previous.id) : previous)?.focus?.();
    lastFocusedBeforeApproval = null;
}

function parseRoute() {
    const hash = window.location.hash.replace(/^#/, "") || (isMockMode() ? "/fleet" : "/scan");
    const parts = hash.split("/").filter(Boolean);
    if (parts[0] === "scan") { return { route: "scan", selectedSiteId: null, selectedAssessmentId: parts[1] ?? null }; }
    if (parts[0] === "run" && parts[1]) {
        return { route: "run", selectedSiteId: parts[1], selectedAssessmentId: null };
    }
    const route = parts[0] || "fleet";
    if (["fleet", "metrics", "recipes", "events"].includes(route)) {
        return { route, selectedSiteId: null, selectedAssessmentId: null };
    }
    return { route: "scan", selectedSiteId: null, selectedAssessmentId: null };
}

function navigate(route, siteId = null) {
    if (route === "scan") {
        window.location.hash = `#/scan${siteId ? `/${encodeURIComponent(siteId)}` : ""}`;
        patchUi({ route: "scan", selectedSiteId: null, selectedAssessmentId: siteId, websiteConnectionError: null });
        refreshWebsiteState();
    } else if (route === "run" && siteId) {
        window.location.hash = `#/run/${siteId}`;
        patchUi({ route: "run", selectedSiteId: siteId, runError: null });
        refreshRunIfNeeded();
    } else {
        window.location.hash = `#/${route}`;
        patchUi({ route, selectedSiteId: null, runLoading: false, runError: null });
    }
    requestAnimationFrame(() => document.getElementById("app-main")?.focus({ preventScroll: true }));
}

function anySiteActive(sites) {
    const active = new Set([
        "assessing",
        "awaiting_approval",
        "staging",
        "testing",
        "candidate_rejected",
        "revising",
        "activating",
        "rechecking",
        "finalizing",
    ]);
    return sites.some((s) => active.has(s.status));
}

function runInProgress(run) {
    if (!run) {
        return false;
    }
    return run.outcome == null || run.outcome === "";
}

function shouldPollFast(snapshot) {
    const { ui, sites, runs, busy } = snapshot;
    if (busy || anySiteActive(sites)) {
        return true;
    }
    if (ui.route === "run" && ui.selectedSiteId) {
        return runInProgress(runs[ui.selectedSiteId]);
    }
    return false;
}

async function loadApprovalPlan(siteId) {
    const request = ++assessmentRequest;
    if (!siteId) {
        patchUi({ approvalPlan: null });
        return;
    }
    try {
        patchUi({ approvalLoading: true, approvalError: null });
        const plan = await getPlanPreview(getState().ui.approvalSiteIds ?? [siteId]);
        if (request === assessmentRequest && getState().ui.approvalSiteId === siteId) {
            patchUi({ approvalPlan: plan, approvalLoading: false });
        }
    } catch (err) {
        if (request === assessmentRequest && getState().ui.approvalSiteId === siteId) {
            patchUi({ approvalPlan: null, approvalLoading: false, approvalError: err.message });
        }
    }
}

function openApproval(siteId) {
    const snapshot = getState();
    if (snapshot.busy || snapshot.ui.preparing || snapshot.ui.resetting || (!isMockMode() && (!snapshot.health?.ready || !snapshot.health?.prepared))) {
        return;
    }
    lastFocusedBeforeApproval = document.activeElement;
    patchUi({ approvalSiteId: siteId, approvalSiteIds: [siteId], repairQueue: [], approvalPlan: null, approvalLoading: true, approvalError: null });
    loadApprovalPlan(siteId);
}

function startRepairAll(siteIds) {
    if (getState().busy || !siteIds.length) {
        return;
    }
    lastFocusedBeforeApproval = document.activeElement;
    const [first, ...rest] = siteIds;
    patchUi({
        approvalSiteId: first,
        approvalSiteIds: isMockMode() ? [first] : siteIds,
        repairQueue: isMockMode() ? rest : [],
        approvalPlan: null,
        approvalLoading: true,
        approvalError: null,
    });
    loadApprovalPlan(first);
}

function closeApproval() {
    if (getState().ui.approvalSubmitting) { return; }
    assessmentRequest += 1;
    patchUi({
        approvalSiteId: null,
        approvalPlan: null,
        approvalSiteIds: [],
        approvalError: null,
        repairQueue: [],
    });
    restoreApprovalFocus();
}

async function onApprove(siteId) {
    const { ui } = getState();
    if (getState().busy || ui.approvalSubmitting || ui.approvalLoading) {
        return;
    }
    try {
        patchUi({ approvalSubmitting: true, approvalError: null });
        const result = await approveAndRepair(ui.approvalSiteIds ?? [siteId], { seedFault: ui.seedFault, plan: ui.approvalPlan });
        await refreshState();
        await refreshEvents();
        const queue = getState().ui.repairQueue;
        if (queue.length) {
            const [next, ...rest] = queue;
            patchUi({
                approvalSiteId: next,
                approvalSiteIds: [next],
                repairQueue: rest,
                approvalPlan: null,
            });
            loadApprovalPlan(next);
        } else {
            patchUi({ approvalSiteId: null, approvalPlan: null });
            restoreApprovalFocus();
            if (result?.runId || isMockMode()) { navigate("run", siteId); }
        }
    } catch (err) {
        patchUi({ approvalError: err?.message ?? "Approval failed" });
    } finally {
        patchUi({ approvalSubmitting: false });
    }
}

const fleetHandlers = {
    openApproval,
    startRepairAll,
    onRefreshState: () => refreshState(),
    onViewActivity: () => navigate("events"),
    onSiteFilter: (siteFilter) => patchUi({ siteFilter }),
    onSelectSite: (siteUrl) => {
        patchUi({ siteUrl, urlError: null });
        document.getElementById("registered-site-url")?.focus();
    },
    viewRun: (siteId) => navigate("run", siteId),
    onPrepare: async () => {
        if (getState().busy || getState().ui.preparing) { return; }
        patchUi({ preparing: true, lastErrorMessage: null });
        try {
            await postPrepare();
            await refreshState();
        } catch (err) {
            patchUi({ lastErrorMessage: err.message });
        } finally { patchUi({ preparing: false }); }
    },
    onAssessUrl: (value) => {
        try {
            const siteId = matchRegisteredUrl(value, getState().sites);
            patchUi({ urlError: null });
            openApproval(siteId);
        } catch (err) {
            patchUi({ urlError: err.message });
            document.getElementById("registered-site-url")?.focus();
        }
    },
    onUrlChange: (value) => patchUi({ siteUrl: value, urlError: null }),
};

const approvalHandlers = {
    closeApproval,
    onApprove,
    onRetry: () => loadApprovalPlan(getState().ui.approvalSiteId),
};

const runHandlers = {
    onBack: () => navigate("fleet"),
    onToggleMode: () => {
        const ownerMode = getState().ui.ownerMode !== false;
        patchUi({ ownerMode: !ownerMode });
    },
};

const eventsHandlers = {
    onFilterSite: (siteId) => patchUi({ eventLogSiteFilter: siteId }),
    onToggleAutoScroll: (enabled) => patchUi({ eventLogAutoScroll: enabled }),
};

const websiteHandlers = {
    repository: repositoryRepairHandlers,
    onUrlChange: (websiteUrl) => patchUi({ websiteUrl, websiteError: null }, { render: Boolean(getState().ui.websiteError) }),
    onExample: (websiteUrl) => {
        patchUi({ websiteUrl, websiteError: null });
        document.getElementById("website-url")?.focus();
    },
    onSelect: (id) => navigate("scan", id),
    onRefresh: () => refreshWebsiteState(true),
    onSubmit: async (input) => {
        if (getState().ui.websiteSubmitting) { return; }
        let url;
        try { url = validateWebsiteUrl(input); }
        catch (err) {
            patchUi({ websiteError: err.message });
            document.getElementById("website-url")?.focus();
            return;
        }
        patchUi({ websiteSubmitting: true, websiteError: null, websiteUrl: url });
        try {
            const result = await createWebsiteAssessment(url);
            navigate("scan", result.assessmentId);
            await refreshWebsiteState(true);
        } catch (err) {
            patchUi({ websiteError: err.message });
        } finally { patchUi({ websiteSubmitting: false }); }
    },
};

async function refreshWebsiteState(forceHistory = false) {
    if (getState().ui.route !== "scan") { return; }
    if (websiteRefresh) {
        await websiteRefresh;
        if (forceHistory) { return refreshWebsiteState(true); }
        return;
    }
    const requestedSelection = getState().ui.selectedAssessmentId;
    websiteRefresh = (async () => {
        const selected = requestedSelection;
        const current = getState().websiteReports[selected];
        const loadHistory = forceHistory || !getState().websiteLoaded;
        const errors = [];
        const requests = [];
        if (loadHistory) { requests.push(["history", getWebsiteAssessmentHistory()]); }
        if (!getState().websiteExamplesLoaded || forceHistory) { requests.push(["examples", getWebsiteExamples()]); }
        if (selected && (forceHistory || !current || WEBSITE_ACTIVE_STATES.has(current.state))) {
            requests.push(["report", getWebsiteAssessment(decodeURIComponent(selected))]);
        }
        const results = await Promise.allSettled(requests.map(([, request]) => request));
        const update = {};
        results.forEach((result, index) => {
            const kind = requests[index][0];
            if (result.status === "rejected") {
                errors.push(`${kind === "examples" ? "Public samples unavailable: " : ""}${result.reason.message}`);
                return;
            }
            if (kind === "examples") { update.websiteExamplesLoaded = true; }
            if (kind === "history") { update.websiteLoaded = true; }
            const value = result.value;
            const field = kind === "history" ? "websiteHistory" : kind === "examples" ? "websiteExamples" : "websiteReports";
            const previous = kind === "report" ? getState().websiteReports[selected] : getState()[field];
            if (JSON.stringify(previous) !== JSON.stringify(value)) {
                update[field] = kind === "report" ? { ...getState().websiteReports, [selected]: value } : value;
            }
        });
        const ui = getState().ui;
        const error = errors.join(" ") || null;
        if (ui.websiteLoading || ui.websiteConnectionError !== error) {
            update.ui = { ...ui, websiteLoading: false, websiteConnectionError: error };
        }
        if (Object.keys(update).some((key) => update[key] !== getState()[key])) { patchState(update); }
        const latest = getState().websiteReports[getState().ui.selectedAssessmentId];
        refreshRepositoryRepairs(latest);
        if (getState().ui.route === "scan") {
            if (pollTimer) { clearTimeout(pollTimer); pollTimer = null; }
            if (WEBSITE_ACTIVE_STATES.has(latest?.state) || getState().ui.websiteSubmitting || errors.length) {
                schedulePoll(WEBSITE_ACTIVE_STATES.has(latest?.state) || getState().ui.websiteSubmitting);
            }
        }
    })().finally(() => {
        websiteRefresh = null;
        if (getState().ui.route === "scan" && getState().ui.selectedAssessmentId !== requestedSelection) {
            refreshWebsiteState();
        }
    });
    return websiteRefresh;
}

async function refreshCurrent() {
    if (getState().ui.route === "scan") { await refreshWebsiteState(); return; }
    stopRepositoryRepairPolling();
    await refreshState();
    await refreshEvents();
    await refreshRunIfNeeded();
}

async function reloadAllEvents() {
    try {
        const events = await getEvents(0);
        replaceEvents(events);
        resetEventsScrollTracking();
    } catch {
        replaceEvents([]);
    }
}

async function handleResetFleet(clearMemory) {
    if (getState().busy || getState().ui.resetting) {
        return;
    }
    patchUi({ resetting: true, lastErrorMessage: null });
    try {
        await postReset({ clear_memory: Boolean(clearMemory) });
        closeApproval();
        patchState({ runs: {} });
        patchUi({ lastErrorMessage: null, clearRecipes: false });
        await refreshState();
        await reloadAllEvents();
    } catch (err) {
        patchUi({ lastErrorMessage: err?.message ?? "Reset failed" });
    } finally {
        patchUi({ resetting: false });
    }
}

const demoHandlers = {
    onClearMemoryChange: (clearRecipes) => patchUi({ clearRecipes }),
    onResetFleet: (clearMemory) => {
        handleResetFleet(clearMemory);
    },
    onSeedFaultChange: (enabled) => patchUi({ seedFault: enabled }),
};

async function refreshState() {
    try {
        const data = await fetchAppState();
        patchState({
            busy: Boolean(data.busy),
            advisory: data.advisory ?? null,
            sites: data.sites ?? [],
            metrics: data.metrics ?? null,
            recipes: data.recipes ?? [],
            recipesAvailable: data.recipesAvailable ?? false,
            health: data.health ?? null,
        });
        patchUi({ backendUnreachable: false, loading: false });
        schedulePoll(
            shouldPollFast({
                ...getState(),
                busy: Boolean(data.busy),
                sites: data.sites ?? [],
            }),
        );
    } catch (err) {
        patchUi({
            backendUnreachable: !isMockMode(),
            lastErrorMessage: err?.message ?? "Request failed",
            loading: false,
        });
        schedulePoll(false);
    }
}

async function refreshEvents() {
    const { lastEventId } = getState();
    try {
        const events = await getEvents(lastEventId);
        appendEvents(events);
    } catch {
        /* keep last events */
    }
}

async function refreshRunIfNeeded() {
    const { ui, runs } = getState();
    if (ui.route !== "run" || !ui.selectedSiteId) {
        return;
    }
    const siteId = ui.selectedSiteId;
    if (!runs[siteId]) {
        patchUi({ runLoading: true, runError: null });
    }
    try {
        const run = await getRun(siteId);
        if (getState().ui.selectedSiteId !== siteId) {
            return;
        }
        if (run) {
            setRun(siteId, run);
        }
        patchUi({ runLoading: false, runError: null });
    } catch {
        patchUi({
            runLoading: false,
            runError: "Could not refresh run. Showing last known data.",
        });
    }
}

function schedulePoll(active) {
    if (pollTimer) {
        clearTimeout(pollTimer);
    }
    const delay = active ? POLL_ACTIVE_MS : POLL_IDLE_MS;
    pollTimer = setTimeout(async () => {
        await refreshCurrent();
    }, delay);
}

function renderMainPanel(container, snapshot) {
    clearElement(container);
    const { ui } = snapshot;

    if (ui.route === "scan") { renderWebsite(container, snapshot, websiteHandlers); return; }

    if (ui.route === "run" && ui.selectedSiteId) {
        renderRun(container, snapshot, runHandlers);
        return;
    }

    if (ui.route === "fleet") {
        renderFleet(container, snapshot, fleetHandlers);
        return;
    }

    if (ui.route === "metrics") {
        renderMetrics(container, snapshot);
        return;
    }

    if (ui.route === "recipes") {
        renderRecipes(container, snapshot);
        return;
    }

    if (ui.route === "events") {
        renderEvents(container, snapshot, eventsHandlers);
        return;
    }
}

function syncApprovalEscape(snapshot) {
    if (snapshot.ui.approvalSiteId) {
        if (!approvalEscapeUnbind) {
            approvalEscapeUnbind = bindApprovalEscape(closeApproval);
        }
    } else if (approvalEscapeUnbind) {
        approvalEscapeUnbind();
        approvalEscapeUnbind = null;
    }
}

function renderApp(snapshot) {
    const focused = document.activeElement;
    const focusedId = focused?.id;
    const inputValue = ["registered-site-url", "website-url", "repository-url"].includes(focusedId) ? focused.value : null;
    const selection = inputValue != null ? [focused.selectionStart, focused.selectionEnd] : null;
    const disclosureState = [...document.querySelectorAll("details[id]")].map((detail) => [detail.id, detail.open]);
    const scrollState = [...document.querySelectorAll(".table-scroll[id], .drawer__body[id], #event-log-scroll-region")]
        .map((region) => [region.id, region.scrollLeft, region.scrollTop]);
    const headerEl = document.getElementById("app-header");
    const navEl = document.getElementById("app-nav");
    const bannerEl = document.getElementById("backend-banner");
    const mainEl = document.getElementById("app-main");
    const approvalEl = document.getElementById("approval-root");
    const liveEl = document.getElementById("live-announcer");

    renderHeader(headerEl, {
        advisory: snapshot.advisory,
        busy: snapshot.busy || snapshot.ui.preparing || snapshot.ui.resetting,
        mockMode: snapshot.ui.mockMode || isMockMode(),
        health: snapshot.health,
        route: snapshot.ui.route,
        websiteReport: snapshot.websiteReports[snapshot.ui.selectedAssessmentId],
        websiteSubmitting: snapshot.ui.websiteSubmitting,
        websiteLoading: snapshot.ui.websiteLoading,
    });
    renderNav(navEl, {
        route: snapshot.ui.route === "run" ? "fleet" : snapshot.ui.route,
        onNavigate: (r) => navigate(r),
        health: snapshot.health,
    });
    renderBackendBanner(bannerEl, {
        visible: snapshot.ui.route !== "scan" && (snapshot.ui.backendUnreachable || Boolean(snapshot.ui.lastErrorMessage)),
        message: snapshot.ui.lastErrorMessage,
        onUseDemo: () => {
            patchState({ runs: {} });
            replaceEvents([]);
            resetEventsScrollTracking();
            enableMockModeFromUi();
            refreshState();
            refreshEvents();
        },
    });

    mainEl.setAttribute("aria-busy", snapshot.ui.route === "scan" ? snapshot.ui.websiteSubmitting ? "true" : "false" : snapshot.busy || snapshot.ui.preparing || snapshot.ui.resetting ? "true" : "false");
    renderMainPanel(mainEl, snapshot);
    const labControls = document.querySelector(".aside");
    if (labControls) { labControls.hidden = snapshot.ui.route === "scan"; }

    if (approvalEl) {
        renderApproval(approvalEl, snapshot, approvalHandlers);
    }
    syncApprovalEscape(snapshot);

    const modalOpen = Boolean(snapshot.ui.approvalSiteId);
    for (const background of [headerEl, navEl, mainEl, document.querySelector(".aside"), bannerEl]) {
        if (background) { background.inert = modalOpen; }
    }
    document.body.classList.toggle("has-modal", modalOpen);
    const scanReport = snapshot.websiteReports[snapshot.ui.selectedAssessmentId];
    const operation = snapshot.ui.route === "scan" ? `website-${scanReport?.state ?? (snapshot.ui.websiteSubmitting ? "submitting" : "ready")}` : snapshot.ui.loading ? "loading" : snapshot.ui.preparing ? "preparing" : snapshot.ui.resetting ? "resetting" : snapshot.busy ? "repairing"
        : !snapshot.health?.ready || !snapshot.health?.prepared ? "setup" : "ready";
    if (liveEl && operation !== liveEl.dataset.lastOperation) {
        liveEl.dataset.lastOperation = operation;
        liveEl.dataset.lastBusy = String(snapshot.busy);
        liveEl.textContent = snapshot.ui.route === "scan" ? scanReport?.stageMessage ?? (snapshot.ui.websiteSubmitting ? "Starting website assessment." : "Ready to assess a public website.") : operation === "ready" ? "Workspace ready."
            : operation === "loading" ? "Checking workspace readiness."
                : operation === "setup" ? "Workspace setup required before assessment."
            : operation === "preparing" ? "Preparing the registered demo sites."
                : operation === "resetting" ? "Restoring the demo baseline."
                    : "Repair in progress. Follow the recorded checks.";
    }

    const demoRoot = document.getElementById("demo-controls-root");
    if (demoRoot) {
        renderDemoControls(demoRoot, snapshot, demoHandlers);
    }
    for (const [id, open] of disclosureState) {
        const replacement = document.getElementById(id);
        if (replacement?.tagName === "DETAILS") { replacement.open = open; }
    }
    for (const [id, left, top] of scrollState) {
        const region = document.getElementById(id);
        if (region) { region.scrollLeft = left; region.scrollTop = top; }
    }
    if (focusedId) {
        const replacement = document.getElementById(focusedId);
        if (replacement && !replacement.disabled) {
            if (inputValue != null) { replacement.value = inputValue; }
            replacement.focus({ preventScroll: true });
            if (selection && replacement.setSelectionRange) {
                replacement.setSelectionRange(...selection);
            }
        }
    }
    if (snapshot.ui.route === "events") { afterRenderEvents(snapshot); }
}

function bindGlobalHandlers() {
    document.querySelector(".skip-link")?.addEventListener("click", (event) => {
        event.preventDefault();
        document.getElementById("app-main")?.focus({ preventScroll: false });
    });
    window.addEventListener("hashchange", () => {
        const { route, selectedSiteId, selectedAssessmentId } = parseRoute();
        patchUi({ route, selectedSiteId, selectedAssessmentId, runError: null });
        document.title = `${route === "scan" ? "Website assessment" : route === "run" ? "Repair report" : route === "events" ? "Lab activity" : "Repair lab"} · sewn`;
        document.getElementById("app-main")?.focus({ preventScroll: true });
        refreshCurrent();
    });

    const demoToggle = document.getElementById("demo-controls-toggle");
    demoToggle?.addEventListener("click", () => {
        const open = !getState().ui.demoControlsOpen;
        patchUi({ demoControlsOpen: open });
        demoToggle.setAttribute("aria-expanded", open ? "true" : "false");
        const panel = document.getElementById("demo-controls-panel");
        if (panel) {
            panel.hidden = !open;
        }
    });
}

function showBootError(err) {
    const mainEl = document.getElementById("app-main");
    if (!mainEl) {
        return;
    }
    clearElement(mainEl);
    const message = err?.message ? String(err.message) : "Unknown error";
    mainEl.append(
        el("h2", { className: "panel__title" }, "Dashboard failed to start"),
        el(
            "p",
            { className: "panel__lede" },
            "sewn could not finish loading. Open the browser developer console for details.",
        ),
        el("p", { className: "panel__status", attrs: { role: "alert" } }, message),
    );
    console.error("sewn boot failed:", err);
}

async function boot() {
    try {
        initApiFromUrl();
        const { route, selectedSiteId, selectedAssessmentId } = parseRoute();
        const requestedUrl = new URLSearchParams(window.location.search).get("url")?.slice(0, 2048) ?? "";
        patchUi({ route, selectedSiteId, selectedAssessmentId, mockMode: isMockMode(), siteUrl: requestedUrl, websiteUrl: requestedUrl });
        document.title = `${route === "scan" ? "Website assessment" : "Repair lab"} · sewn`;

        subscribe(renderApp);
        bindGlobalHandlers();
        renderApp(getState());

        await refreshCurrent();
    } catch (err) {
        showBootError(err);
    }
}

window.addEventListener("pagehide", () => {
    stopRepositoryRepairPolling();
    if (pollTimer) {
        clearTimeout(pollTimer);
    }
    if (approvalEscapeUnbind) {
        approvalEscapeUnbind();
    }
    disposeMockTimers();
});

boot();
