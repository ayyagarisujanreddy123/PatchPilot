import { el } from "../util.js";
import { websiteTimestamp } from "../website.js";
import { REPOSITORY_ACTIVE_STATES, hasPublishableProof, safePullRequestUrl } from "../repositoryRepairModel.js";
import { canRetryPublication } from "../repositoryRepairs.js";

const labels = { QUEUED: "Waiting to prepare", FETCHING: "Fetching pinned source", BASELINE: "Checking baseline behavior", PLANNING: "Victor is preparing the candidate", STAGING: "Testing the candidate", READY_TO_PUBLISH: "Tested candidate ready", NO_CHANGE: "No supported change needed", REJECTED: "Candidate rejected", PUBLISHING: "Creating a draft pull request", PUBLISHED: "Draft pull request created", FAILED: "Repair could not finish" };

function proof(report) {
    const phases = ["BASELINE", "CANDIDATE"];
    return el("div", { className: "repository-repair__proof" }, phases.map((phase) => {
        const checks = report.checks.filter((check) => check.phase === phase);
        return el("section", {}, [el("h4", {}, phase === "BASELINE" ? "Before the change" : "With the candidate"),
            el("p", { className: "repository-repair__count" }, checks.length ? `${checks.filter((check) => check.passed).length} of ${checks.length} checks passed` : "No check results recorded"),
            el("ul", {}, checks.map((check) => el("li", { className: check.passed ? "is-passed" : "is-failed" }, [
                el("strong", {}, `${check.passed ? "Passed" : "Failed"} · ${check.label}`),
                el("details", { id: `repository-check-${report.repairId}-${check.phase}-${check.checkId}` }, [el("summary", {}, "Expected & observed"),
                    el("p", {}, `Expected: ${check.expected}`), el("p", {}, `Observed: ${check.observed}`), el("p", { className: "muted" }, `${check.durationMs} ms`)]),
            ]))),
        ]);
    }));
}

function provenance(report) {
    const proposal = report.proposal;
    return el("details", { className: "repository-repair__disclosure", id: `repository-provenance-${report.repairId}` }, [
        el("summary", { id: `repository-provenance-summary-${report.repairId}` }, "AI provenance & execution limits"),
        proposal ? el("div", {}, [el("p", {}, proposal.rationale), el("dl", { className: "website-facts" }, [
            ["Provider", "Anthropic"], ["Model", proposal.modelId], ["Provider message", proposal.providerMessageId], ["Input / output tokens", `${proposal.inputTokens} / ${proposal.outputTokens}`],
            ["Base commit", report.baseCommit], ["Sandbox image", report.imageDigest ?? "Not recorded"], ["Created", websiteTimestamp(report.createdAt)], ["Finished", report.finishedAt ? websiteTimestamp(report.finishedAt) : "In progress"],
        ].map(([key, value]) => el("div", {}, [el("dt", {}, key), el("dd", {}, value)])))]) : el("p", {}, "No validated Anthropic proposal has been recorded."),
        el("ul", {}, report.limitations.map((item) => el("li", {}, item))),
    ]);
}

export function renderRepositoryRepairReport(report, data, handlers) {
    const active = REPOSITORY_ACTIVE_STATES.has(report.state);
    const failed = ["FAILED", "REJECTED"].includes(report.state);
    const ready = hasPublishableProof(report);
    const retry = canRetryPublication(report);
    const prUrl = report.state === "PUBLISHED" ? safePullRequestUrl(report) : null;
    const publication = ready || retry ? el("button", { className: "btn btn--primary", id: "repository-publish", attrs: { type: "button", disabled: data.busyAction ? "disabled" : undefined } }, data.busyAction === "publish" ? "Submitting publication…" : retry ? "Retry pull-request publication" : "Create draft pull request") : null;
    publication?.addEventListener("click", () => handlers.onPublish(report));
    const eventLog = el("details", { className: "repository-repair__disclosure", id: `repository-events-${report.repairId}` }, [
        el("summary", { id: `repository-events-summary-${report.repairId}` }, `Recorded repair activity · ${report.events.length} updates`),
        el("ol", { className: "website-event-list" }, report.events.map((event) => el("li", {}, [el("time", { attrs: { datetime: event.timestamp } }, websiteTimestamp(event.timestamp)), el("strong", {}, event.state === "PLANNING" ? "Victor" : event.state), el("span", {}, event.message)]))),
    ]);
    return el("section", { className: "repository-repair__report", attrs: { "aria-labelledby": "repository-repair-heading" } }, [
        el("div", { className: `repository-repair__status${active ? " is-active" : ""}${failed ? " is-failed" : ""}` }, [active ? el("span", { className: "website-spinner", attrs: { "aria-hidden": "true" } }) : null,
            el("div", {}, [el("h3", { id: "repository-repair-heading", attrs: { tabindex: "-1" } }, labels[report.state]), el("p", { id: "repository-stage-message", attrs: { role: failed ? "alert" : "status" } }, report.stageMessage), report.error ? el("p", {}, report.error) : null])]),
        report.checks.length ? proof(report) : null,
        report.patch ? el("details", { className: "repository-repair__disclosure", id: `repository-diff-${report.repairId}` }, [
            el("summary", { id: `repository-diff-summary-${report.repairId}` }, `Review exact diff · ${report.patch.path}`),
            el("pre", {}, el("code", {}, report.patch.unifiedDiff)),
            el("p", { className: "muted" }, `Source blob: ${report.patch.beforeBlobSha} · Candidate SHA-256: ${report.patch.afterSha256}`),
        ]) : null,
        eventLog, provenance(report),
        ready ? el("p", {}, "The candidate passed its recorded checks. Baseline results show the original behavior and configuration. Review both and the exact diff before publishing a draft pull request.") : null,
        retry ? el("p", {}, "The previous publication attempt did not finish. This retries the same publication request; it does not prepare another candidate.") : null,
        publication,
        prUrl ? el("a", { className: "btn btn--primary", id: "repository-pr-link", attrs: { href: prUrl, target: "_blank", rel: "noopener noreferrer" } }, `Open ${report.pullRequest.draft ? "draft " : ""}pull request #${report.pullRequest.number}`) : report.state === "PUBLISHED" ? el("p", {}, `Pull request recorded: ${report.pullRequest?.url ?? "URL not available"}`) : null,
        report.state === "PUBLISHED" ? el("p", { className: "repository-repair__scope" }, "The pull request has not been deployed. Merge, deployment, and production verification remain under your control.") : null,
    ]);
}
