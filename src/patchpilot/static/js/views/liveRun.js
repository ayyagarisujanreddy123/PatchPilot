/** Evidence view for actual API records, including explicit test doubles. */
import { el, formatDuration } from "../util.js";
import { groupChecks } from "../live.js";
import { planSourceLabel, renderPlanSourceBadge } from "./badges.js";

const CHECK_LABELS = {
    runtime_version: "PHP version",
    sapi: "HTTP serving mode",
    upload_progress: "Upload-session mitigation",
    deployment_identity: "Tested deployment identity",
    homepage: "Homepage content",
    contact_valid: "Contact form accepts valid input",
    contact_invalid: "Contact form rejects invalid input",
    upload_size: "3 MiB upload byte count",
    upload_hash: "3 MiB upload SHA-256",
};

const PROGRESS_STEPS = ["Assess", "Prepare candidate", "Verify candidate", "Activate & recheck"];
const ACTIVE_STEP = {
    QUEUED: 0, ASSESSING: 0, PLANNING: 1, REVISING: 1, STAGING: 1,
    VERIFYING: 2, ACTIVATING: 3, LIVE_VERIFYING: 3,
};
const RECOVERY_STATES = new Set(["RESTORING", "RESTORED", "RECOVERY_FAILED"]);

function value(data) {
    if (data == null) { return "Not recorded"; }
    return typeof data === "string" ? data : JSON.stringify(data, null, 2);
}

function evidenceComplete(run) {
    return run.raw.siteResults?.[run.siteId]?.evidenceComplete
        ?? run.report?.evidenceComplete ?? run.raw.evidenceComplete;
}

function renderProgress(run, prefix) {
    const recovered = RECOVERY_STATES.has(run.state);
    const verified = run.state === "VERIFIED" && evidenceComplete(run) === true;
    const current = ACTIVE_STEP[run.state] ?? (run.state === "REJECTED" ? 2 : run.state === "VERIFIED" ? 3 : null);
    const checkpoint = run.raw.checkpoint?.state;
    const interruptedAt = ACTIVE_STEP[checkpoint]
        ?? (["ACTIVATING", "LIVE_VERIFYING", "RESTORING", "RESTORED", "VERIFIED"].includes(checkpoint) ? 3 : null);
    const steps = PROGRESS_STEPS.map((label, index) => {
        let state = "pending";
        let status = "Not confirmed";
        if (verified || (!recovered && current != null && index < current) || (recovered && interruptedAt != null && index < interruptedAt)) {
            state = "complete";
            status = "Completed";
        } else if (!recovered && index === current) {
            state = run.state === "REJECTED" ? "failed" : "current";
            status = run.state === "REJECTED" ? "Rejected" : run.state === "QUEUED" ? "Queued" : "Current step";
        } else if (recovered && index === interruptedAt) {
            state = checkpoint === "VERIFIED" ? "complete" : "failed";
            status = checkpoint === "VERIFIED" ? "Completed before recovery" : "Stopped before recovery";
        }
        return { label, state, status };
    });
    if (recovered) {
        steps.push({
            label: "Restore original",
            state: run.state === "RESTORED" ? "complete" : run.state === "RECOVERY_FAILED" ? "failed" : "current",
            status: run.state === "RESTORED" ? "Restored, still unpatched" : run.state === "RECOVERY_FAILED" ? "Recovery failed" : "Restoring",
        });
    }
    return el("section", { className: "run-progress-section", attrs: { "aria-labelledby": `${prefix}-progress-title` } }, [
        el("h2", { id: `${prefix}-progress-title`, className: "run-section-title" }, "Repair progress"),
        el("p", { className: "run-muted" }, `Recorded worker state: ${run.state ?? "Not recorded"}. Check results below determine the outcome.`),
        el("ol", { className: "run-progress", attrs: { "aria-label": "Recorded repair progress" } }, steps.map((step) => el("li", {
            className: "run-progress__step", dataset: { state: step.state },
            attrs: { "aria-current": step.state === "current" ? "step" : undefined },
        }, [
            el("span", { className: "run-progress__label" }, step.label),
            el("span", { className: "run-progress__status" }, step.status),
        ]))),
    ]);
}

function renderSummary(run, groups) {
    const passed = groups.current.filter((check) => check.passed === true).length;
    const failed = groups.current.filter((check) => check.passed === false).length;
    const outcomes = Object.values(run.raw.siteResults ?? {}).filter((result) => result.state || result.outcome).length;
    const scope = run.raw.siteIds?.length;
    const stat = (label, result) => el("div", { className: "run-summarystrip__item" }, [el("dt", {}, label), el("dd", {}, result)]);
    return el("dl", { className: "run-summarystrip", attrs: { "aria-label": "Recorded run summary" } }, [
        stat("Latest phase", groups.phase ?? "No checks yet"),
        stat("Checks recorded", String(groups.current.length)),
        stat("Check results", [
            el("span", { className: "check-pill check-pill--pass" }, `${passed} passed`),
            el("span", { className: `check-pill ${failed ? "check-pill--fail" : "check-pill--neutral"}` }, `${failed} failed`),
        ]),
        stat("Site outcomes recorded", scope ? `${outcomes} of ${scope}` : String(outcomes)),
    ]);
}

function evidenceSection(label, evidence, summary, id) {
    return el("section", { className: "evidence-section" }, [
        el("h2", {}, label),
        el("p", {}, summary ?? (evidence == null ? "Not recorded" : "Recorded evidence is available below.")),
        evidence != null ? el("details", { id }, [
            el("summary", { id: `${id}-summary` }, "Technical evidence"),
            el("pre", {}, value(evidence)),
        ]) : null,
    ]);
}

function renderChecks(checks, run, className) {
    let previousIndex = -1;
    return el("ul", { className: `live-checks ${className}` }, checks.map((check) => {
        const index = run.checks.findIndex((item, position) => position > previousIndex && item === check);
        previousIndex = index;
        const id = `live-check-${encodeURIComponent(run.id)}-${encodeURIComponent(run.siteId)}-${index}`;
        return el("li", {}, [
            el("h3", {}, CHECK_LABELS[check.checkId] ?? check.checkId ?? "Check"),
            el("p", { className: `check-pill ${check.passed === true ? "check-pill--pass" : check.passed === false ? "check-pill--fail" : "check-pill--neutral"}` }, check.passed === true ? "Passed" : check.passed === false ? "Failed" : "Pending"),
            el("p", {}, check.message ?? "No message recorded."),
            el("p", { className: "run-muted" }, `Duration: ${formatDuration(check.durationMs)}`),
            el("details", { id }, [
                el("summary", { id: `${id}-summary` }, "Expected / observed evidence"),
                el("pre", {}, `Check: ${check.checkId} · ${check.phase}\nExpected: ${value(check.expectedValue)}\nObserved: ${value(check.observedValue)}`),
                check.structuredFailure ? el("pre", {}, value(check.structuredFailure)) : null,
            ]),
        ]);
    }));
}

const OUTCOMES = {
    patched_verified: ["verified", "Patched & verified", "The backend reports successful verification at the original local site address."],
    candidate_rejected: ["warn", "Candidate rejected", "The candidate did not satisfy the verification contract. Review the recorded checks."],
    restored_unpatched: ["warn", "Restored — still vulnerable / unpatched", "The original deployment was restored. The security issue remains unresolved."],
    restoration_failed: ["danger", "Restoration failed — human help required", "Review the recovery evidence before further work."],
    needs_help: ["warn", "Repair stopped — review required", "The worker could not complete an automatic repair."],
};

export function renderLiveRun(root, run, health) {
    const record = run.raw;
    const simulation = run.simulation || health?.mode === "SIMULATION";
    const prefix = `report-${encodeURIComponent(run.id)}-${encodeURIComponent(run.siteId)}`;
    const groups = groupChecks(run.checks);
    if (run.historical) {
        root.append(el("p", { className: "approval__note", attrs: { role: "status" } }, "Historical run record. This result does not describe the current deployment after a reset or fresh preparation."));
    }
    root.append(renderProgress(run, prefix), renderSummary(run, groups));
    root.append(el("h2", { id: `${prefix}-title`, className: "run-section-title" }, "Repair report"));
    const incomplete = run.outcome === "patched_verified" && evidenceComplete(run) !== true;
    const [tone, title, body] = incomplete
        ? ["warn", "Verification evidence incomplete", "The worker has not completed durable verification evidence. Review the recorded state before treating this as a successful repair."]
        : OUTCOMES[run.outcome] ?? ["progress", "Repair in progress", "The worker is processing this approved scope. No successful outcome is claimed yet."];
    root.append(el("div", { className: `outcome-banner outcome-banner--${simulation ? "warn" : tone}`, attrs: { role: "status" } }, [
        el("p", { className: "outcome-banner__title" }, simulation ? `Simulation: ${title}` : title),
        el("p", { className: "outcome-banner__body" }, simulation ? "Test-double events and checks are simulated. No real deployment was repaired or verified." : body),
    ]));
    root.append(el("p", { className: "run-note" }, `Run ${record.runId} · site state: ${run.state} · approved scope: ${(record.siteIds ?? []).join(", ")}`));
    const badge = renderPlanSourceBadge(run.plan_source);
    if (badge) { root.append(badge); }
    if (run.error) { root.append(el("p", { className: "hint hint--disabled", attrs: { role: "alert" } }, run.error)); }
    root.append(el("h2", { className: "run-section-title" }, groups.phase ? `${groups.phase === "RESTORATION" ? "Restoration" : groups.phase === "LIVE" ? "Live" : groups.phase === "STAGING" ? "Candidate" : "Baseline"} verification checks` : "Recorded verification checks"));
    if (!run.checks.length) { root.append(el("p", { className: "empty-state" }, "No verification checks have been recorded for this site yet.")); }
    root.append(renderChecks(groups.current, run, "current-checks"));
    if (groups.failures.length) {
        root.append(el("h2", { className: "run-section-title" }, "Earlier failed checks"),
            el("p", { className: "approval__note" }, "These failures remain part of the record. Later live or restoration checks determine the final outcome; earlier candidate failures do not count as successful verification."),
            renderChecks(groups.failures, run, "failed-checks"));
    }
    if (groups.history.length) {
        root.append(el("h2", { className: "run-section-title" }, "Earlier verification history"),
            el("details", { id: `${prefix}-history`, className: "evidence-section" }, [
                el("summary", { id: `${prefix}-history-summary` }, `Show ${groups.history.length} earlier checks`),
                renderChecks(groups.history, run, "historical-checks"),
            ]));
    }
    const report = run.report;
    if (!report) { root.append(el("p", { className: "run-muted" }, "No report is available yet.")); return; }
    root.append(el("section", { className: "evidence-section" }, [
        el("h2", {}, "Changes recorded"),
        report.changes?.length ? el("ul", {}, report.changes.map((change) => el("li", {}, value(change)))) : el("p", {}, "No changes recorded."),
    ]));
    const security = report.securityResults;
    const securitySummary = security ? [
        security.liveVerified === true ? "Live verification passed." : security.liveVerified === false ? "Live verification did not pass for the complete run scope." : "",
        security.fixedPhpVersion ? `Policy fixed release: PHP ${security.fixedPhpVersion}.` : "",
        security.scope ?? "",
    ].filter(Boolean).join(" ") || "See recorded security evidence." : null;
    root.append(
        evidenceSection("Run security results", security, securitySummary, `${prefix}-security`),
        evidenceSection("Run recovery evidence", report.recovery, report.recovery == null ? "No recovery evidence recorded." : null, `${prefix}-recovery`),
        evidenceSection("Site planning provenance", run.provenance,
            [planSourceLabel(run.plan_source), run.provenance?.modelId, run.provenance?.note].filter(Boolean).join(" · "), `${prefix}-provenance`),
    );
    if (report.warnings?.length) { root.append(el("section", { className: "evidence-section" }, [el("h2", {}, "Warnings"), el("ul", {}, report.warnings.map((warning) => el("li", {}, value(warning))))])); }
    root.append(el("p", { className: "run-muted" }, "The Event log contains ordered worker events. Historical success describes this run; a later reset can restore a vulnerable baseline."));
}
