import { el } from "../util.js";
import { icon } from "../icons.js";
import { REPOSITORY_ACTIVE_STATES } from "../repositoryRepairModel.js";
import { repositoryConnectForm, repositorySetupInstructions } from "./repositoryRepairSetup.js";
import { renderRepositoryRepairReport } from "./repositoryRepairReport.js";

function connectionSummary(connection) {
    return el("div", { className: "repository-repair__connection" }, [
        el("h3", {}, connection.repository), el("p", {}, connection.identityExplanation),
        el("dl", { className: "website-facts" }, [["Pinned base commit", connection.baseCommit], ["Default branch", connection.defaultBranch], ["Selected checks", connection.capabilities.join(", ")]].map(([key, value]) => el("div", {}, [el("dt", {}, key), el("dd", {}, value)]))),
        el("details", { className: "repository-repair__disclosure", id: `repository-manifest-${connection.connectionId}` }, [el("summary", {}, "View connected manifest"), el("pre", {}, el("code", {}, JSON.stringify(connection.manifest, null, 2)))]),
    ]);
}

export function renderRepositoryRepair(snapshot, assessment, handlers) {
    if (assessment.state !== "COMPLETED") { return null; }
    const data = snapshot.repositoryRepairs[assessment.assessmentId] ?? {};
    const connection = data.connection;
    const report = data.report;
    const active = REPOSITORY_ACTIVE_STATES.has(report?.state);
    const retry = el("button", { className: "btn btn--ghost btn--small", id: "repository-refresh", attrs: { type: "button", disabled: data.loading || data.busyAction ? "disabled" : undefined } }, "Refresh connection & repair status");
    retry.addEventListener("click", () => handlers.onRefresh(assessment.assessmentId));
    const connect = el("details", { className: "repository-repair__connect", id: `repository-repair-next-step-${assessment.assessmentId}` }, [
        el("summary", { id: `repository-repair-next-step-summary-${assessment.assessmentId}` }, [icon("code"), connection ? `Connected · ${connection.repository}` : "Connect your GitHub repository", el("span", { className: "repository-repair__expand", attrs: { "aria-hidden": "true" } }, "+")]),
        data.loading ? el("p", { attrs: { role: "status" } }, "Loading repository connection status…") : null,
        connection ? connectionSummary(connection) : null,
        connection ? el("details", { className: "repository-repair__disclosure", id: "repository-change-connection" }, [el("summary", { id: "repository-change-connection-summary" }, "Connect another repository or change checks"), repositoryConnectForm(snapshot, assessment.assessmentId, data, handlers)]) : repositoryConnectForm(snapshot, assessment.assessmentId, data, handlers),
        repositorySetupInstructions(), retry,
    ]);
    const prepare = connection && !active && report?.state !== "PUBLISHED" && report?.state !== "READY_TO_PUBLISH" ? el("button", { className: "btn btn--primary", id: "repository-prepare", attrs: { type: "button", disabled: data.busyAction ? "disabled" : undefined } }, data.busyAction === "prepare" ? "Starting isolated checks…" : "Prepare tested fix") : null;
    prepare?.addEventListener("click", () => handlers.onPrepare(connection));
    return el("section", { className: "repository-repair", attrs: { "aria-labelledby": "repository-next-step-heading" } }, [
        el("p", { className: "eyebrow" }, "OWNER NEXT STEP"), el("h2", { id: "repository-next-step-heading" }, "Prepare a tested fix"),
        el("p", { className: "repository-repair__intro" }, "Connect your source, preserve selected business checks, and review a tested PHP configuration change. You choose whether to create a draft pull request."),
        connect,
        data.fetchError || data.actionError ? el("div", { className: "field-error", id: "repository-repair-error", attrs: { role: "alert", tabindex: "-1" } }, [el("p", {}, data.actionError ?? data.fetchError), el("p", {}, "Recorded evidence is retained. Refresh status before retrying an operation.")]) : null,
        prepare,
        connection && !report ? el("p", { className: "repository-repair__scope" }, "Preparation reads the pinned source and runs isolated checks. It does not push to GitHub or deploy your website.") : null,
        report ? renderRepositoryRepairReport(report, data, handlers) : null,
        el("p", { className: "repository-repair__scope" }, "Supported scope: PHP error display, logging, and version-banner configuration. This does not repair every finding or change the live website."),
    ]);
}
