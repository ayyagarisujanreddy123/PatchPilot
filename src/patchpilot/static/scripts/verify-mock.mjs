/**
 * Mock API checklist (run from static/: node scripts/verify-mock.mjs)
 */
import { createMockApi } from "../js/mock.js";

globalThis.window ??= {};
globalThis.window.location ??= { search: "" };

function setScenario(scenario) {
    const q = scenario && scenario !== "default" ? `?mock=1&scenario=${scenario}` : "?mock=1";
    globalThis.window.location.search = q;
}

function sleep(ms) {
    return new Promise((r) => setTimeout(r, ms));
}

async function waitUntilIdle(api, maxMs = 20000) {
    const start = Date.now();
    while (Date.now() - start < maxMs) {
        const s = await api.getState();
        if (!s.busy) {
            return s;
        }
        await sleep(200);
    }
    throw new Error("timeout waiting for busy=false");
}

async function runFleetStory(seedFault = true) {
    setScenario("default");
    const api = createMockApi({ getUiSeedFault: () => seedFault });
    api.activate(false);

    await api.postRepair({ site_ids: ["site-a"], seed_fault: false });
    await waitUntilIdle(api);
    let st = await api.getState();
    if (st.sites.find((x) => x.id === "site-a").status !== "patched_verified") {
        throw new Error(`site-a: ${st.sites.find((x) => x.id === "site-a").status}`);
    }
    if (st.recipes.length < 1) {
        throw new Error("missing basic recipe after site-a");
    }

    await api.postRepair({ site_ids: ["site-b"], seed_fault: seedFault });
    await waitUntilIdle(api);
    st = await api.getState();
    if (st.sites.find((x) => x.id === "site-b").status !== "patched_verified") {
        throw new Error(`site-b: ${st.sites.find((x) => x.id === "site-b").status}`);
    }
    if (seedFault && (st.metrics.rejections ?? 0) < 1) {
        throw new Error("expected staging rejections >= 1");
    }
    if (st.recipes.length < 2) {
        throw new Error("missing upload recipe after site-b");
    }

    await api.postRepair({ site_ids: ["site-c"], seed_fault: false });
    await waitUntilIdle(api);
    st = await api.getState();
    if (st.sites.find((x) => x.id === "site-c").status !== "patched_verified") {
        throw new Error(`site-c: ${st.sites.find((x) => x.id === "site-c").status}`);
    }
    if ((st.recipes.find((r) => r.origin_site === "site-a")?.reuse_count ?? 0) < 1) {
        throw new Error("site-a reuse_count not incremented");
    }

    await api.postRepair({ site_ids: ["site-d"], seed_fault: false });
    await waitUntilIdle(api);
    st = await api.getState();
    if (st.sites.find((x) => x.id === "site-d").status !== "patched_verified") {
        throw new Error(`site-d: ${st.sites.find((x) => x.id === "site-d").status}`);
    }
    if ((st.recipes.find((r) => r.origin_site === "site-b")?.reuse_count ?? 0) < 1) {
        throw new Error("site-b reuse_count not incremented");
    }

    return st;
}

async function testReset() {
    setScenario("default");
    const api = createMockApi({ getUiSeedFault: () => false });
    api.activate(false);
    await api.postRepair({ site_ids: ["site-a"], seed_fault: false });
    await waitUntilIdle(api);
    await api.postReset({ clear_memory: false });
    let st = await api.getState();
    if (st.recipes.length < 1) {
        throw new Error("recipes not kept when clear_memory false");
    }
    if (!st.sites.every((s) => s.status === "vulnerable")) {
        throw new Error("fleet not reset to vulnerable");
    }
    await api.postReset({ clear_memory: true });
    st = await api.getState();
    if (st.recipes.length !== 0) {
        throw new Error("recipes not cleared when clear_memory true");
    }
}

async function testBatchQueue() {
    setScenario("default");
    const api = createMockApi({ getUiSeedFault: () => false });
    api.activate(false);
    await api.postRepair({ site_ids: ["site-a", "site-c"], seed_fault: false });
    await waitUntilIdle(api);
    const st = await api.getState();
    if (st.sites.find((x) => x.id === "site-a").status !== "patched_verified") {
        throw new Error("batch: site-a not patched");
    }
    if (st.sites.find((x) => x.id === "site-c").status !== "patched_verified") {
        throw new Error("batch: site-c not patched after queue");
    }
}

async function testScenario(scenario, expectedStatus, expectedOutcomeCheck) {
    setScenario(scenario);
    const api = createMockApi({ getUiSeedFault: () => false });
    api.activate(false);
    await api.postRepair({ site_ids: ["site-a"], seed_fault: false });
    await waitUntilIdle(api);
    const st = await api.getState();
    const site = st.sites.find((x) => x.id === "site-a");
    if (site.status !== expectedStatus) {
        throw new Error(`expected status ${expectedStatus}, got ${site.status}`);
    }
    const run = await api.getRun("site-a");
    expectedOutcomeCheck(run, st);
}

const lines = [];
let failed = false;

function pass(msg) {
    lines.push(`PASS: ${msg}`);
}
function fail(msg) {
    lines.push(`FAIL: ${msg}`);
    failed = true;
}

try {
    const st = await runFleetStory(true);
    pass(`A→B(seed)→C→D (patched ${st.metrics.sites_patched}/4, rejections ${st.metrics.rejections}, rollbacks ${st.metrics.rollbacks})`);
} catch (e) {
    fail(`A→B→C→D — ${e.message}`);
}

try {
    await testReset();
    pass("Reset fleet (keep recipes / clear recipes)");
} catch (e) {
    fail(`Reset — ${e.message}`);
}

try {
    await testBatchQueue();
    pass("Mock repairQueue dequeue (multi-site POST)");
} catch (e) {
    fail(`Batch queue — ${e.message}`);
}

try {
    await testScenario("rollback", "restored_unpatched", (run, st) => {
        if (run.outcome !== "restored_unpatched") {
            throw new Error(`outcome ${run.outcome}`);
        }
        if ((st.metrics.rollbacks ?? 0) < 1) {
            throw new Error("rollbacks metric not incremented");
        }
    });
    pass("scenario=rollback (site-a restored, still vulnerable)");
} catch (e) {
    fail(`scenario=rollback — ${e.message}`);
}

try {
    await testScenario("restorefail", "restoration_failed", (run, st) => {
        if (run.outcome !== "restoration_failed") {
            throw new Error(`outcome ${run.outcome}`);
        }
        if ((st.metrics.sites_needing_help ?? 0) < 1) {
            throw new Error("sites_needing_help not incremented");
        }
    });
    pass("scenario=restorefail (restoration failed)");
} catch (e) {
    fail(`scenario=restorefail — ${e.message}`);
}

for (const line of lines) {
    console.log(line);
}

console.log("");
console.log("Browser checks: open ?mock=1, review demo controls, narrow layouts, and keyboard navigation. Live reset uses POST /api/resets and its status resource.");

process.exit(failed ? 1 : 0);
