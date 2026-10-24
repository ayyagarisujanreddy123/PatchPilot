/** Resource API values adapted for the dashboard. Evidence is never synthesized. */

const STATES = {
    QUEUED: "queued", ASSESSING: "assessing", PLANNING: "planning",
    STAGING: "staging", VERIFYING: "testing", REVISING: "revising",
    ACTIVATING: "activating", LIVE_VERIFYING: "rechecking", RESTORING: "restoring",
    VERIFIED: "patched_verified", REJECTED: "candidate_rejected",
    BLOCKED: "needs_help", RESTORED: "restored_unpatched",
    RECOVERY_FAILED: "restoration_failed", INTERRUPTED: "needs_help",
};

export const TERMINAL_STATES = new Set([
    "VERIFIED", "REJECTED", "BLOCKED", "RESTORED", "RECOVERY_FAILED", "INTERRUPTED",
]);

export function normalizeState(state) {
    return STATES[state] ?? "unknown";
}

export function normalizeSite(site, run = null, assessment = null) {
    const runtime = assessment?.currentRuntime ?? {};
    const result = run?.siteResults?.[site.siteId];
    const state = result?.state ?? result?.outcome ?? (run?.currentSiteId && run.currentSiteId !== site.siteId ? "QUEUED" : run?.state);
    const observed = result?.final ?? (run?.currentSiteId === site.siteId ? run.originalIdentity : null) ?? {};
    const allChecks = (result?.checks ?? run?.checks ?? []).filter((check) => !check.siteId || check.siteId === site.siteId);
    const latestPhase = ["RESTORATION", "LIVE", "STAGING", "BASELINE"].find((phase) => allChecks.some((check) => check.phase === phase));
    const checks = allChecks.filter((check) => check.phase === latestPhase);
    return {
        id: site.siteId,
        org_name: site.displayName,
        address: site.baseUrl,
        type: site.capabilities?.includes("upload") ? "upload" : "basic",
        capabilities: site.capabilities ?? [],
        php_version: site.phpVersion ?? observed.phpVersion ?? observed.php_version ?? runtime.phpVersion ?? null,
        sapi: site.sapi ?? observed.sapi ?? runtime.sapi ?? null,
        status: run ? normalizeState(state) : assessment?.canRepair ? "vulnerable" : "unassessed",
        plan_source: result?.planSource ?? run?.planSource ?? null,
        checks_passed: checks.length ? checks.filter((check) => check.passed).length : null,
        checks_required: checks.length || null,
        attempts: run?.attempt ?? null,
        last_run_id: run?.runId ?? site.lastRunId ?? null,
    };
}

export function normalizeRun(record, report = null, siteId = null) {
    const siteResult = report?.siteResults?.[siteId] ?? record.siteResults?.[siteId];
    const state = siteResult?.state ?? siteResult?.outcome ?? (siteId && record.currentSiteId && siteId !== record.currentSiteId ? "QUEUED" : record.state);
    const source = siteResult?.planSource ?? record.planSource;
    const perSiteProvenance = siteResult?.provenance ?? (record.siteIds?.length > 1
        ? { source: siteResult?.planSource ?? null, note: "Per-site provider details were not recorded for this run." }
        : report?.provenance ?? record.provenance);
    return {
        id: record.runId,
        siteId,
        isLiveRecord: true,
        raw: record,
        report,
        outcome: TERMINAL_STATES.has(state) ? normalizeState(state) : null,
        state,
        plan_source: source,
        provenance: perSiteProvenance,
        simulation: source === "TEST_DOUBLE",
        checks: (siteResult?.checks ?? report?.checks ?? record.checks ?? []).filter((check) => !siteId || !check.siteId || check.siteId === siteId),
        error: siteResult ? siteResult.error : record.currentSiteId === siteId ? record.error : null,
    };
}

export function normalizeEvent(event, runId) {
    return {
        id: `${runId}:${event.sequence}`,
        run_id: runId,
        sequence: event.sequence,
        ts: event.timestamp,
        site_id: event.siteId,
        stage: event.state,
        message: event.message,
        check: event.check,
    };
}

/** Keep final evidence and every failure visible; retain earlier passing checks. */
export function groupChecks(checks) {
    const phase = ["RESTORATION", "LIVE", "STAGING", "BASELINE"].find((item) => checks.some((check) => check.phase === item));
    const current = phase ? checks.filter((check) => check.phase === phase) : checks;
    const failures = checks.filter((check) => check.passed === false && !current.includes(check));
    const history = checks.filter((check) => !current.includes(check) && !failures.includes(check));
    return { phase, current, failures, history };
}

/** Exact registered loopback origins only; this never requests the supplied URL. */
export function matchRegisteredUrl(input, sites) {
    let requested;
    try {
        requested = new URL(input);
    } catch {
        throw new Error("Enter a complete registered local URL, such as http://127.0.0.1:8081.");
    }
    const local = ["127.0.0.1", "localhost", "[::1]"].includes(requested.hostname);
    if (!local || requested.protocol !== "http:") {
        throw new Error("This address needs an authorized hosting connection. This prototype assesses only its registered local PHP fixtures.");
    }
    if (requested.username || requested.password || requested.search || requested.hash || requested.pathname !== "/") {
        throw new Error("Use the registered site base URL without credentials, a path, query, or fragment.");
    }
    const match = sites.find((site) => {
        try { return new URL(site.address).href === requested.href; } catch { return false; }
    });
    if (!match) {
        throw new Error("This local URL is not registered. Select one of the configured fleet addresses below.");
    }
    return match.id;
}
