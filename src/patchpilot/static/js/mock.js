/**
 * Scripted demo data and mock API — timed fleet narrative for ?mock=1.
 */

import { scenarioFromUrl } from "./util.js";

export const WORKFLOW_STAGES = [
    { key: "inspect_baseline", label: "Inspect / baseline" },
    { key: "choose_plan", label: "Choose plan" },
    { key: "validate_stage", label: "Validate & stage" },
    { key: "verify_candidate", label: "Verify candidate" },
    { key: "reject_or_revise", label: "Reject or revise" },
    { key: "activate_recheck", label: "Activate & recheck" },
    { key: "restore", label: "Restore (if required)" },
    { key: "commit_evidence", label: "Commit evidence" },
];

export const ADVISORY = {
    title: "PHP 8.3.36 emergency release",
    fixed_version: "8.3.36",
    cves: ["CVE-2026-109618", "CVE-2026-109619"],
    mitigation_note:
        "session.upload_progress.enabled=0 retained as a separate conservative mitigation (CVE-2026-115560).",
};

const BASE_CONFIG = [
    { key: "session.upload_progress.enabled", value: "0" },
];

function uploadConfig(seedFault) {
    if (seedFault) {
        return [
            ...BASE_CONFIG,
            { key: "upload_max_filesize", value: "2M" },
            { key: "post_max_size", value: "8M" },
        ];
    }
    return [
        ...BASE_CONFIG,
        { key: "upload_max_filesize", value: "8M" },
        { key: "post_max_size", value: "10M" },
    ];
}

/**
 * Plan preview for approval drawer (mock). Live backend may expose the same shape later.
 */
export function getPlanPreview(siteId, options = {}) {
    const { seedFault = false, recipesAvailable = false } = options;
    const targetImage = "patchpilot/php-8.3.36-apache";
    const targetPhp = "8.3.36";

    if (siteId === "site-a") {
        return {
            plan_source: "fresh_model",
            target_image: targetImage,
            target_php_version: targetPhp,
            config: [...BASE_CONFIG],
            rationale:
                "Upgrade the serving PHP runtime to the vendor fixed release while keeping conservative upload-session mitigation.",
            finding_plain: null,
        };
    }

    if (siteId === "site-b") {
        const useSeed = seedFault;
        return {
            plan_source: useSeed ? "seeded_fault" : "fresh_model",
            target_image: targetImage,
            target_php_version: targetPhp,
            config: uploadConfig(useSeed),
            rationale: useSeed
                ? "Demo seeded candidate with a 2M upload limit to trigger staging rejection (deliberately incompatible)."
                : "Upgrade PHP and preserve 8M upload / 10M POST limits required for the 3 MiB verification upload.",
            finding_plain: null,
        };
    }

    if (siteId === "site-c" && recipesAvailable) {
        return {
            plan_source: "verified_recipe_reuse",
            target_image: targetImage,
            target_php_version: targetPhp,
            config: [...BASE_CONFIG],
            rationale:
                "Apply the verified recipe from Riverbend Food Pantry. Checks will be re-run on this site.",
            finding_plain: null,
        };
    }

    if (siteId === "site-d" && recipesAvailable) {
        return {
            plan_source: "verified_recipe_reuse",
            target_image: targetImage,
            target_php_version: targetPhp,
            config: uploadConfig(false),
            rationale:
                "Apply the verified upload-site recipe from Marco's Family Kitchen. Checks will be re-run on this site.",
            finding_plain: null,
        };
    }

    return {
        plan_source: "fresh_model",
        target_image: targetImage,
        target_php_version: targetPhp,
        config: siteId === "site-d" || siteId === "site-b" ? uploadConfig(false) : [...BASE_CONFIG],
        rationale: "Upgrade the serving PHP runtime to the vendor fixed release.",
        finding_plain: null,
    };
}

function baseSites() {
    return [
        {
            id: "site-a",
            org_name: "Riverbend Food Pantry",
            type: "basic",
            address: "http://127.0.0.1:8081",
            php_version: "8.3.34",
            sapi: "apache2handler",
            status: "vulnerable",
            plan_source: null,
            checks_passed: null,
            checks_required: 6,
            attempts: 0,
        },
        {
            id: "site-b",
            org_name: "Marco's Family Kitchen",
            type: "upload",
            address: "http://127.0.0.1:8082",
            php_version: "8.3.34",
            sapi: "apache2handler",
            status: "vulnerable",
            plan_source: null,
            checks_passed: null,
            checks_required: 6,
            attempts: 0,
        },
        {
            id: "site-c",
            org_name: "Oak Street Community Clinic",
            type: "basic",
            address: "http://127.0.0.1:8083",
            php_version: "8.3.35",
            sapi: "apache2handler",
            status: "vulnerable",
            plan_source: null,
            checks_passed: null,
            checks_required: 6,
            attempts: 0,
        },
        {
            id: "site-d",
            org_name: "Westside Donations Hub",
            type: "upload",
            address: "http://127.0.0.1:8084",
            php_version: "8.3.35",
            sapi: "apache2handler",
            status: "vulnerable",
            plan_source: null,
            checks_passed: null,
            checks_required: 6,
            attempts: 0,
        },
    ];
}

function emptyMetrics() {
    return {
        sites_patched: 0,
        sites_total: 4,
        sites_needing_help: 0,
        rejections: 0,
        rollbacks: 0,
        plan_sources: {},
        recipe_hits: 0,
        planner_invocations: null,
        model_requests: null,
        attempts_total: null,
        checks_passed: null,
        checks_required: null,
        phase_durations_ms: {
            planning: null,
            staging: null,
            testing: null,
            activation: null,
            total: null,
        },
        memory_comparison: null,
    };
}

function configObject(seedFault, revised = false) {
    if (revised || !seedFault) {
        return {
            "session.upload_progress.enabled": "0",
            "upload_max_filesize": "8M",
            "post_max_size": "10M",
        };
    }
    return {
        "session.upload_progress.enabled": "0",
        "upload_max_filesize": "2M",
        "post_max_size": "8M",
    };
}

function basicConfigObject() {
    return { "session.upload_progress.enabled": "0" };
}

function buildChecks(siteType, { uploadPass = true, phpVersion = "8.3.36" } = {}) {
    const checks = [
        {
            key: "serving_runtime",
            label: "Serving runtime",
            expected: `PHP ${phpVersion}, SAPI apache2handler, session.upload_progress.enabled=0`,
            observed: `PHP ${phpVersion}, SAPI apache2handler, session.upload_progress.enabled=0`,
            passed: true,
            evidence: "GET /phpinfo.php (sanitized): version=8.3.36; sapi=apache2handler; ini session.upload_progress.enabled=0",
        },
        {
            key: "homepage_contact",
            label: "Homepage & contact",
            expected: "200 homepage; valid contact accepted; invalid rejected",
            observed: "200 homepage; valid contact 200; invalid contact 422",
            passed: true,
            evidence: "homepage GET 200; contact POST valid=200; invalid=422",
        },
    ];
    if (siteType === "upload") {
        checks.push({
            key: "upload_capability",
            label: "Upload capability",
            expected: "3145728 bytes uploaded; sha256=7d865e959b5563317c1f0d8b67202111038c5a3c6d285136053278d2b0886c9d",
            observed: uploadPass
                ? "3145728 bytes uploaded; sha256=7d865e959b5563317c1f0d8b67202111038c5a3c6d285136053278d2b0886c9d"
                : "413 Request Entity Too Large; 2097152 bytes received (under 3 MiB requirement)",
            passed: uploadPass,
            evidence: uploadPass
                ? "multipart POST 3 MiB file: status 200; stored size=3145728"
                : "multipart POST 3 MiB file: status 413; upload_max_filesize=2M insufficient",
        });
    }
    checks.push({
        key: "activation",
        label: "Activation",
        expected: "Same checks at original address",
        observed: uploadPass
            ? "All activation checks passed at original address"
            : "Activation not reached (staging rejected)",
        passed: uploadPass,
        evidence: uploadPass ? "activation suite passed at registered localhost port" : "n/a — candidate rejected at staging",
    });
    return checks;
}

function initialStages(runningKey = "inspect_baseline") {
    return WORKFLOW_STAGES.map((s) => ({
        key: s.key,
        state: s.key === runningKey ? "running" : "pending",
        duration_ms: null,
    }));
}

function setStagesThrough(run, throughKey, { runningKey = null, skippedAfter = null } = {}) {
    const order = WORKFLOW_STAGES.map((s) => s.key);
    const throughIdx = order.indexOf(throughKey);
    for (let i = 0; i < run.stages.length; i += 1) {
        const key = run.stages[i].key;
        const idx = order.indexOf(key);
        if (idx < throughIdx) {
            run.stages[i].state = "passed";
            run.stages[i].duration_ms = run.stages[i].duration_ms ?? 400 + idx * 120;
        } else if (key === throughKey) {
            run.stages[i].state = runningKey ? "running" : "passed";
            if (!runningKey) {
                run.stages[i].duration_ms = run.stages[i].duration_ms ?? 500;
            }
        } else if (skippedAfter != null && idx > order.indexOf(skippedAfter)) {
            run.stages[i].state = "skipped";
        } else if (idx > throughIdx) {
            run.stages[i].state = "pending";
        }
    }
    if (runningKey) {
        const ri = run.stages.findIndex((s) => s.key === runningKey);
        if (ri >= 0) {
            run.stages[ri].state = "running";
        }
    }
}

function createInitialRun(siteId, planSource, config) {
    return {
        id: `mock-run-${siteId}`,
        site_id: siteId,
        outcome: null,
        stages: initialStages(),
        attempts: [
            {
                n: 1,
                plan_source: planSource,
                config,
                result: null,
                checks: [],
            },
        ],
        rejections: 0,
        rollbacks: 0,
        durations_ms: {
            planning: null,
            staging: null,
            testing: null,
            activation: null,
            total: null,
        },
    };
}

function schedule(delayMs, fn) {
    const id = setTimeout(fn, delayMs);
    timers.push(id);
    return id;
}

function bumpPlanSource(key) {
    if (!key) {
        return;
    }
    mockState.metrics.plan_sources = mockState.metrics.plan_sources ?? {};
    mockState.metrics.plan_sources[key] = (mockState.metrics.plan_sources[key] ?? 0) + 1;
}

function syncAggregateMetrics() {
    const sites = mockState.sites;
    mockState.metrics.sites_patched = sites.filter((s) => s.status === "patched_verified").length;
    mockState.metrics.sites_needing_help = sites.filter((s) =>
        ["restoration_failed", "needs_help"].includes(s.status),
    ).length;
    mockState.metrics.attempts_total = sites.reduce((sum, s) => sum + (s.attempts ?? 0), 0);
}

function onMockRunFinished() {
    syncAggregateMetrics();
    mockState.busy = false;
    if (mockState.repairQueue?.length) {
        const next = mockState.repairQueue.shift();
        mockState.busy = true;
        schedule(200, () => applyRepairStart(next, mockState.seedFault));
    }
}

function markStagesPassed(run) {
    run.stages.forEach((s) => {
        if (s.state === "pending" || s.state === "running") {
            s.state = "passed";
        }
        s.duration_ms = s.duration_ms ?? 450;
    });
}

function finalizeSuccessfulRun(siteId, run, site, started) {
    markStagesPassed(run);
    const checks = buildChecks(site.type, { uploadPass: true });
    run.attempts[0].checks = checks;
    run.attempts[0].result = "passed";
    run.outcome = "patched_verified";
    site.status = "patched_verified";
    run.durations_ms = {
        planning: 800,
        staging: 950,
        testing: 1200,
        activation: 700,
        total: Date.now() - started,
    };
    mockState.metrics.phase_durations_ms = { ...run.durations_ms };
    site.checks_passed = checks.filter((c) => c.passed).length;
    site.checks_required = checks.length;
    bumpPlanSource(run.attempts[0].plan_source);
    if (siteId === "site-a") {
        commitBasicSiteRecipe(siteId, run);
    } else if (siteId === "site-b") {
        commitUploadSiteRecipe(siteId, run, { hadRejection: false });
    } else if (siteId === "site-c" || siteId === "site-d") {
        recordRecipeReuse(siteId, run);
    }
    pushEvent(siteId, "commit_evidence", `${site.org_name}: patched and verified (mock).`);
    onMockRunFinished();
}

function startSimpleRunPlayback(siteId, planSource) {
    const site = findSite(siteId);
    if (!site) {
        return;
    }
    const run = createInitialRun(siteId, planSource, site.type === "upload" ? configObject(false, true) : basicConfigObject());
    mockState.runs[siteId] = run;
    const started = Date.now();

    const steps = [
        { t: 600, status: "assessing", through: "inspect_baseline", running: "choose_plan" },
        { t: 1200, status: "staging", through: "choose_plan", running: "validate_stage" },
        { t: 1800, status: "testing", through: "validate_stage", running: "verify_candidate" },
        { t: 2600, status: "activating", through: "verify_candidate", running: "activate_recheck" },
        { t: 3400, status: "rechecking", through: "activate_recheck", running: "commit_evidence" },
        { t: 4200, status: "patched_verified", through: "commit_evidence", finalize: true },
    ];

    for (const step of steps) {
        schedule(step.t, () => {
            site.status = step.status;
            setStagesThrough(run, step.through, { runningKey: step.running ?? null });
            if (step.finalize) {
                finalizeSuccessfulRun(siteId, run, site, started);
            }
        });
    }
}

function startRollbackPlayback(siteId) {
    const site = findSite(siteId);
    if (!site) {
        return;
    }
    const run = createInitialRun(siteId, "fresh_model", basicConfigObject());
    mockState.runs[siteId] = run;
    const started = Date.now();

    schedule(600, () => {
        site.status = "assessing";
        setStagesThrough(run, "inspect_baseline", { runningKey: "choose_plan" });
    });
    schedule(1200, () => {
        site.status = "staging";
        setStagesThrough(run, "choose_plan", { runningKey: "validate_stage" });
    });
    schedule(1900, () => {
        site.status = "testing";
        const checks = buildChecks(site.type, { uploadPass: true });
        run.attempts[0].checks = checks;
        run.attempts[0].result = "passed";
        setStagesThrough(run, "validate_stage", { runningKey: "verify_candidate" });
    });
    schedule(2700, () => {
        site.status = "activating";
        setStagesThrough(run, "verify_candidate", { runningKey: "activate_recheck" });
    });
    schedule(3500, () => {
        site.status = "rechecking";
        run.rollbacks = 1;
        mockState.metrics.rollbacks = (mockState.metrics.rollbacks ?? 0) + 1;
        bumpPlanSource("fresh_model");
        setStagesThrough(run, "activate_recheck", { runningKey: "restore" });
        pushEvent(siteId, "activate_recheck", "Live recheck failed after activation (mock rollback demo).");
    });
    schedule(4300, () => {
        site.status = "restored_unpatched";
        run.outcome = "restored_unpatched";
        setStagesThrough(run, "restore");
        run.stages.forEach((s) => {
            if (s.key === "commit_evidence") {
                s.state = "skipped";
            }
        });
        run.durations_ms = {
            planning: 700,
            staging: 900,
            testing: 1100,
            activation: 600,
            total: Date.now() - started,
        };
        mockState.metrics.phase_durations_ms = { ...run.durations_ms };
        site.php_version = "8.3.34";
        pushEvent(
            siteId,
            "restore",
            `${site.org_name}: original runtime restored — still vulnerable (mock).`,
        );
        onMockRunFinished();
    });
}

function startRestoreFailPlayback(siteId) {
    const site = findSite(siteId);
    if (!site) {
        return;
    }
    const run = createInitialRun(siteId, "fresh_model", basicConfigObject());
    mockState.runs[siteId] = run;
    const started = Date.now();

    schedule(600, () => {
        site.status = "assessing";
        setStagesThrough(run, "inspect_baseline", { runningKey: "choose_plan" });
    });
    schedule(1200, () => {
        site.status = "staging";
        setStagesThrough(run, "choose_plan", { runningKey: "validate_stage" });
    });
    schedule(1900, () => {
        site.status = "testing";
        run.attempts[0].checks = buildChecks(site.type, { uploadPass: true });
        run.attempts[0].result = "passed";
        setStagesThrough(run, "validate_stage", { runningKey: "verify_candidate" });
    });
    schedule(2700, () => {
        site.status = "activating";
        setStagesThrough(run, "verify_candidate", { runningKey: "activate_recheck" });
        pushEvent(siteId, "activate_recheck", "Activation failed at live address (mock).");
    });
    schedule(3500, () => {
        site.status = "needs_help";
        run.rollbacks = 1;
        mockState.metrics.rollbacks = (mockState.metrics.rollbacks ?? 0) + 1;
        setStagesThrough(run, "activate_recheck", { runningKey: "restore" });
    });
    schedule(4300, () => {
        site.status = "restoration_failed";
        run.outcome = "restoration_failed";
        const restoreStage = run.stages.find((s) => s.key === "restore");
        if (restoreStage) {
            restoreStage.state = "failed";
        }
        run.stages.forEach((s) => {
            if (s.key === "commit_evidence") {
                s.state = "skipped";
            }
        });
        mockState.metrics.sites_needing_help = (mockState.metrics.sites_needing_help ?? 0) + 1;
        bumpPlanSource("fresh_model");
        run.durations_ms = { planning: 700, staging: 850, testing: 1000, activation: 500, total: Date.now() - started };
        mockState.metrics.phase_durations_ms = { ...run.durations_ms };
        pushEvent(siteId, "restore", "Restoration failed — needs human help (mock).");
        onMockRunFinished();
    });
}

function startSiteBRunPlayback(seedFault) {
    const siteId = "site-b";
    const site = findSite(siteId);
    if (!site) {
        return;
    }
    const useSeed = seedFault !== false;
    const run = createInitialRun(siteId, useSeed ? "seeded_fault" : "fresh_model", configObject(useSeed, false));
    mockState.runs[siteId] = run;
    const started = Date.now();

    schedule(700, () => {
        site.status = "assessing";
        setStagesThrough(run, "inspect_baseline", { runningKey: "choose_plan" });
    });
    schedule(1400, () => {
        site.status = "staging";
        setStagesThrough(run, "choose_plan", { runningKey: "validate_stage" });
    });
    schedule(2100, () => {
        site.status = "testing";
        setStagesThrough(run, "validate_stage", { runningKey: "verify_candidate" });
    });
    schedule(2900, () => {
        const failChecks = buildChecks("upload", { uploadPass: false });
        run.attempts[0].checks = failChecks;
        run.attempts[0].result = "candidate_rejected";
        run.rejections = 1;
        mockState.metrics.rejections = 1;
        site.status = "candidate_rejected";
        site.checks_passed = failChecks.filter((c) => c.passed).length;
        site.checks_required = failChecks.length;
        setStagesThrough(run, "verify_candidate", { runningKey: "reject_or_revise" });
        pushEvent(siteId, "verify_candidate", "3 MiB upload check failed — candidate rejected (mock).");
    });
    schedule(3700, () => {
        site.status = "revising";
        setStagesThrough(run, "reject_or_revise");
        run.attempts.push({
            n: 2,
            plan_source: "fresh_model",
            config: configObject(false, true),
            result: null,
            checks: [],
        });
        site.attempts = 2;
        site.plan_source = "fresh_model";
        pushEvent(siteId, "reject_or_revise", "Revised plan: upload_max_filesize 8M, post_max_size 10M (mock).");
    });
    schedule(4500, () => {
        site.status = "testing";
        setStagesThrough(run, "reject_or_revise", { runningKey: "verify_candidate" });
    });
    schedule(5300, () => {
        const passChecks = buildChecks("upload", { uploadPass: true });
        run.attempts[1].checks = passChecks;
        run.attempts[1].result = "passed";
        site.checks_passed = passChecks.filter((c) => c.passed).length;
        setStagesThrough(run, "verify_candidate", { runningKey: "activate_recheck" });
    });
    schedule(6100, () => {
        site.status = "activating";
        setStagesThrough(run, "activate_recheck", { runningKey: "commit_evidence" });
    });
    schedule(6900, () => {
        site.status = "patched_verified";
        run.outcome = "patched_verified";
        setStagesThrough(run, "commit_evidence");
        run.stages.forEach((s) => {
            if (s.state !== "skipped") {
                s.state = "passed";
            }
            s.duration_ms = s.duration_ms ?? 520;
        });
        run.durations_ms = {
            planning: 900,
            staging: 1100,
            testing: 2400,
            activation: 800,
            total: Date.now() - started,
        };
        mockState.metrics.phase_durations_ms = { ...run.durations_ms };
        bumpPlanSource("fresh_model");
        bumpPlanSource("seeded_fault");
        commitUploadSiteRecipe(siteId, run, { hadRejection: true });
        pushEvent(siteId, "commit_evidence", "Marco's Family Kitchen: patched and verified after revision (mock).");
        onMockRunFinished();
    });
}

function startRunPlayback(siteId, seedFault) {
    const site = findSite(siteId);
    if (!site) {
        return;
    }

    if (siteId === "site-a" && mockState.scenario === "rollback") {
        site.plan_source = "fresh_model";
        startRollbackPlayback(siteId);
        return;
    }
    if (siteId === "site-a" && mockState.scenario === "restorefail") {
        site.plan_source = "fresh_model";
        startRestoreFailPlayback(siteId);
        return;
    }

    const preview = getPlanPreview(siteId, {
        seedFault: seedFault && siteId === "site-b",
        recipesAvailable: recipesAvailableForSite(siteId),
    });
    site.plan_source = preview.plan_source;

    if (siteId === "site-b") {
        const useSeed = Boolean(seedFault);
        if (useSeed) {
            startSiteBRunPlayback(true);
        } else {
            startSimpleRunPlayback(siteId, preview.plan_source);
        }
        return;
    }

    startSimpleRunPlayback(siteId, preview.plan_source);
}

let mockState = null;
let eventSeq = 0;
let timers = [];

function pushEvent(siteId, stage, message) {
    eventSeq += 1;
    mockState.events.push({
        id: eventSeq,
        ts: new Date().toISOString(),
        site_id: siteId,
        stage,
        message,
    });
}

function findSite(siteId) {
    return mockState.sites.find((s) => s.id === siteId);
}

function recipesAvailableForSite(siteId) {
    if (siteId === "site-c") {
        return mockState.recipes.some((r) => r.origin_site === "site-a");
    }
    if (siteId === "site-d") {
        return mockState.recipes.some((r) => r.origin_site === "site-b");
    }
    return (mockState.recipes?.length ?? 0) > 0;
}

function commitBasicSiteRecipe(siteId, run) {
    if (siteId !== "site-a") {
        return;
    }
    if (mockState.recipes.some((r) => r.origin_site === siteId)) {
        return;
    }
    mockState.recipes.push({
        key_summary:
            "advisory: CERT-EU 2026-018 rev A\nimage: patchpilot/php-8.3.36-apache\nruntime: php-8.3\nsapi: apache2handler\ntemplate: basic-homepage-contact v1\ncapabilities: homepage, contact\nini: session.upload_progress.enabled=0\ntests: contract v1",
        origin_site: siteId,
        origin_run: run.id,
        verified_at: new Date().toISOString(),
        reuse_count: 0,
        failure_notes: [],
    });
    pushEvent(siteId, "commit_evidence", "Verified recipe saved to memory (mock).");
}

function commitUploadSiteRecipe(siteId, run, { hadRejection = false } = {}) {
    if (siteId !== "site-b") {
        return;
    }
    if (mockState.recipes.some((r) => r.origin_site === siteId)) {
        return;
    }
    mockState.recipes.push({
        key_summary:
            "advisory: CERT-EU 2026-018 rev A\nimage: patchpilot/php-8.3.36-apache\nruntime: php-8.3\nsapi: apache2handler\ntemplate: upload-homepage-contact v1\ncapabilities: homepage, contact, upload_3mib\nini: session.upload_progress.enabled=0; upload_max_filesize=8M; post_max_size=10M\ntests: contract v1",
        origin_site: siteId,
        origin_run: run.id,
        verified_at: new Date().toISOString(),
        reuse_count: 0,
        failure_notes: hadRejection
            ? ["Staging rejection: 3 MiB upload failed when upload_max_filesize=2M (demo seeded fault)."]
            : [],
    });
    pushEvent(siteId, "commit_evidence", "Verified upload-site recipe saved to memory (mock).");
}

function recordRecipeReuse(siteId, run) {
    const originSite = siteId === "site-c" ? "site-a" : siteId === "site-d" ? "site-b" : null;
    if (!originSite) {
        return;
    }
    const recipe = mockState.recipes.find((r) => r.origin_site === originSite);
    if (!recipe) {
        return;
    }
    recipe.reuse_count = (recipe.reuse_count ?? 0) + 1;
    mockState.metrics.recipe_hits = (mockState.metrics.recipe_hits ?? 0) + 1;
    pushEvent(siteId, "choose_plan", `Verified recipe reused from ${originSite}; checks re-run on this site (mock).`);
}

function applyRepairStart(siteId, seedFault) {
    const site = findSite(siteId);
    if (!site) {
        return;
    }
    const preview = getPlanPreview(siteId, {
        seedFault: seedFault && siteId === "site-b",
        recipesAvailable: recipesAvailableForSite(siteId),
    });
    site.status = "assessing";
    site.plan_source = preview.plan_source;
    site.attempts = (site.attempts ?? 0) + 1;
    pushEvent(siteId, "inspect_baseline", `Repair started for ${site.org_name} (mock).`);
    startRunPlayback(siteId, seedFault);
}

function resetMockState(seedFault, { clearMemory = true } = {}) {
    for (const t of timers) {
        clearTimeout(t);
    }
    timers = [];
    eventSeq = 0;
    const preservedRecipes =
        !clearMemory && mockState?.recipes?.length
            ? mockState.recipes.map((r) => ({ ...r }))
            : [];
    mockState = {
        busy: false,
        advisory: ADVISORY,
        sites: baseSites(),
        metrics: emptyMetrics(),
        recipes: preservedRecipes,
        events: [],
        runs: {},
        scenario: scenarioFromUrl(),
        seedFault,
        repairQueue: [],
        _started: false,
    };
    pushEvent(null, "system", "Mock demo loaded. Fleet at vulnerable baseline (4 sites).");
}

export function createMockApi(options = {}) {
    const { getUiSeedFault } = options;

    function ensureInit() {
        if (!mockState) {
            resetMockState(Boolean(getUiSeedFault?.()));
        }
    }

    function currentSeedFault() {
        return Boolean(mockState?.seedFault ?? getUiSeedFault?.());
    }

    return {
        mode: "mock",

        getPlanPreview(siteId) {
            ensureInit();
            return getPlanPreview(siteId, {
                seedFault: currentSeedFault(),
                recipesAvailable: recipesAvailableForSite(siteId),
            });
        },

        async getState() {
            ensureInit();
            return {
                busy: mockState.busy,
                advisory: mockState.advisory,
                sites: mockState.sites.map((s) => ({ ...s })),
                metrics: { ...mockState.metrics },
                recipes: mockState.recipes.map((r) => ({ ...r })),
            };
        },

        async getRun(siteId) {
            ensureInit();
            const run = mockState.runs[siteId];
            return run ? JSON.parse(JSON.stringify(run)) : null;
        },

        async getEvents(since) {
            ensureInit();
            const sinceId = Number(since) || 0;
            return mockState.events.filter((e) => e.id > sinceId).map((e) => ({ ...e }));
        },

        async postRepair(body) {
            ensureInit();
            if (mockState.busy) {
                throw new Error("Busy lock active");
            }
            const siteIds = body?.site_ids ?? [];
            if (!siteIds.length) {
                throw new Error("No site_ids provided");
            }
            const seedFault = Boolean(body?.seed_fault);
            mockState.seedFault = seedFault;
            mockState.busy = true;

            const firstId = siteIds[0];
            applyRepairStart(firstId, seedFault);
            mockState.repairQueue = siteIds.slice(1);
            pushEvent(
                null,
                "system",
                siteIds.length > 1
                    ? `Sequential repair queue started (${siteIds.length} sites, mock).`
                    : "Repair started (mock).",
            );

            return { ok: true, site_ids: siteIds };
        },

        async postApprove(_body) {
            ensureInit();
            return { ok: true };
        },

        async postReset(body) {
            ensureInit();
            if (mockState.busy) {
                throw new Error("Busy lock active");
            }
            resetMockState(currentSeedFault(), { clearMemory: Boolean(body?.clear_memory) });
            if (body?.clear_memory) {
                pushEvent(null, "system", "Fleet reset (mock). Recipe memory cleared.");
            } else {
                pushEvent(null, "system", "Fleet reset (mock). Recipe memory kept.");
            }
            return { ok: true };
        },

        activate(seedFault = false) {
            resetMockState(seedFault);
        },

        dispose() {
            for (const t of timers) {
                clearTimeout(t);
            }
            timers = [];
        },
    };
}
