/**
 * Single application store. Views subscribe and re-render from snapshots.
 */

const initialUi = {
    route: "fleet",
    selectedSiteId: null,
    ownerMode: true,
    eventLogAutoScroll: true,
    eventLogSiteFilter: "all",
    demoControlsOpen: false,
    seedFault: false,
    approvalSiteId: null,
    approvalPlan: null,
    repairQueue: [],
    backendUnreachable: false,
    mockMode: false,
    loading: true,
    lastErrorMessage: null,
    runLoading: false,
    runError: null,
};

let state = {
    ui: { ...initialUi },
    busy: false,
    advisory: null,
    sites: [],
    metrics: null,
    recipes: [],
    runs: {},
    events: [],
    lastEventId: 0,
};

const listeners = new Set();

export function getState() {
    return state;
}

export function getUi() {
    return state.ui;
}

export function subscribe(listener) {
    listeners.add(listener);
    return () => listeners.delete(listener);
}

function notify() {
    for (const listener of listeners) {
        listener(state);
    }
}

export function patchState(partial) {
    state = { ...state, ...partial };
    notify();
}

export function patchUi(partial) {
    state = {
        ...state,
        ui: { ...state.ui, ...partial },
    };
    notify();
}

export function setRun(siteId, run) {
    state = {
        ...state,
        runs: { ...state.runs, [siteId]: run },
    };
    notify();
}

export function appendEvents(newEvents) {
    if (!newEvents?.length) {
        return;
    }
    const merged = [...state.events, ...newEvents];
    const last = merged[merged.length - 1];
    state = {
        ...state,
        events: merged,
        lastEventId: last?.id ?? state.lastEventId,
    };
    notify();
}

export function replaceEvents(events) {
    const last = events?.length ? events[events.length - 1] : null;
    state = {
        ...state,
        events: events ?? [],
        lastEventId: last?.id ?? 0,
    };
    notify();
}

export function resetStoreForMock() {
    state = {
        ui: {
            ...initialUi,
            mockMode: true,
            loading: false,
            demoControlsOpen: state.ui.demoControlsOpen,
            seedFault: state.ui.seedFault,
            approvalPlan: null,
            repairQueue: [],
        },
        busy: false,
        advisory: null,
        sites: [],
        metrics: null,
        recipes: [],
        runs: {},
        events: [],
        lastEventId: 0,
    };
    notify();
}
