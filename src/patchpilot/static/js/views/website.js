import { clearElement, el } from "../util.js";
import { icon } from "../icons.js";
import { WEBSITE_ACTIVE_STATES, websiteTimestamp } from "../website.js";
import { evidenceLinks, renderWebsiteEvidence, sourceLink } from "./websiteEvidence.js";
import { renderWebsiteFindings, renderWebsiteAnalysis, renderWebsiteProvenance } from "./websiteFindings.js";
import { renderWebsiteProgress } from "./websiteProgress.js";
import { renderWebsiteStart, renderWebsiteHistory } from "./websiteStart.js";
import { renderRepositoryRepair } from "./repositoryRepair.js";

function overview(report) {
    const collected = report.responses.length > 0;
    const detection = report.phpDetection;
    const php = detection.version ? `PHP ${detection.version}` : detection.status === "INFERRED" ? "PHP signal" : "Unknown";
    const cells = [
        [collected ? String(report.findings.length) : report.state === "FAILED" ? "Not collected" : "Pending", "Findings to review", "findings"],
        [php, detection.status === "REPORTED" ? "Reported by the website" : detection.status === "INFERRED" ? "PHP is not confirmed" : "PHP version not confirmed", "php"],
        [report.analysis ? String(report.analysis.recommendations.length) : report.state === "FAILED" ? "Unavailable" : "Pending", "AI-suggested fixes", "fixes"],
    ];
    return el("dl", { className: "website-overview", attrs: { "aria-label": "Assessment overview" } }, cells.map(([value, label, kind]) => el("div", { className: `website-stat website-stat--${kind}` }, [el("dt", {}, label), el("dd", {}, value)])));
}

function technical(report) {
    return el("details", { className: "website-technical", id: `website-technical-${report.assessmentId}` }, [
        el("summary", { id: `website-technical-summary-${report.assessmentId}` }, [icon("code"), "View technical evidence", el("span", { className: "muted" }, "HTTP, PHP detection & coverage")]),
        el("div", { className: "website-technical__body" }, [
            el("section", { className: "website-php", attrs: { "aria-labelledby": "website-php-heading" } }, [
                el("h3", { id: "website-php-heading" }, "How PHP was detected"),
                el("p", {}, report.phpDetection.explanation), evidenceLinks(report.phpDetection.evidenceIds, report, "php"),
            ]), renderWebsiteEvidence(report), renderWebsiteProvenance(report),
            el("section", { className: "website-section website-coverage" }, [el("h3", {}, "Coverage & limitations"),
                el("h4", {}, "What was checked"), el("ul", {}, report.coverage.map((item) => el("li", {}, item))),
                el("h4", {}, "What remains uncertain"), el("ul", {}, report.limitations.map((item) => el("li", {}, item))),
                el("p", { className: "website-report-meta" }, `Assessment ${report.assessmentId} · Created ${websiteTimestamp(report.createdAt)}`),
            ]),
        ]),
    ]);
}

function reportView(report, handlers) {
    const active = WEBSITE_ACTIVE_STATES.has(report.state);
    const state = { COMPLETED: "Ready to review", FAILED: "Needs a retry", QUEUED: "Queued", COLLECTING: "Collecting evidence", ANALYZING: "AI is analyzing" };
    const root = el("section", { className: "website-report", attrs: { "aria-labelledby": "website-report-heading" } }, [
        el("div", { className: "website-report-heading" }, [el("div", {}, [el("p", { className: "eyebrow" }, "YOUR ASSESSMENT"), el("h2", { id: "website-report-heading" }, sourceLink(report.url)),
            el("span", { className: `website-state website-state--${report.state.toLowerCase()}` }, state[report.state])]),
            el("button", { className: "btn btn--secondary btn--small", attrs: { type: "button", id: "website-rescan", disabled: active ? "disabled" : undefined } }, [icon("refresh"), "Check again"])]),
        renderWebsiteProgress(report),
        report.responses.length || report.analysis ? overview(report) : null,
        renderWebsiteAnalysis(report),
        report.findings.length ? el("details", { className: "website-all-findings", id: `website-findings-${report.assessmentId}` }, [
            el("summary", { id: `website-findings-summary-${report.assessmentId}` }, [icon("book"), `All findings · ${report.findings.length}`, el("span", { className: "muted" }, "What we observed & why it matters")]), renderWebsiteFindings(report),
        ]) : null,
        el("p", { className: "website-scope-note" }, [icon("info"), "Public response assessment. Suggested fixes need your review and server access. No changes have been applied."]),
        technical(report),
    ]);
    root.querySelector("#website-rescan").addEventListener("click", () => handlers.onSubmit(report.url));
    return root;
}

export function renderWebsite(root, snapshot, handlers) {
    clearElement(root);
    const report = snapshot.websiteReports[snapshot.ui.selectedAssessmentId] ?? null;
    const workspace = el("div", { className: `website-workspace${report ? " website-workspace--report" : ""}` }, [
        el("header", { className: "website-heading" }, [el("p", { className: "eyebrow" }, "PHP SECURITY, SIMPLIFIED"), el("h1", {}, report ? "Your website assessment" : "A safer site starts here."),
            el("p", {}, report ? "See what matters. Review the next step." : "Check your PHP website. Understand the risks. Know what to fix.")]),
    ]);
    if (snapshot.ui.websiteConnectionError) { workspace.append(el("p", { className: "field-error", attrs: { role: "alert" } }, snapshot.ui.websiteConnectionError)); }
    if (snapshot.ui.websiteLoading && !report) { workspace.append(el("p", { attrs: { role: "status" } }, "Loading your assessments…")); }
    if (report) {
        workspace.append(reportView(report, handlers));
        const repositoryRepair = renderRepositoryRepair(snapshot, report, handlers.repository);
        if (repositoryRepair) { workspace.append(repositoryRepair); }
        workspace.append(el("details", { className: "website-new-assessment", id: "website-new-assessment" }, [
            el("summary", { id: "website-new-assessment-summary" }, [icon("globe"), "Check another website"]), renderWebsiteStart(snapshot, report, handlers),
        ]));
    } else { workspace.append(renderWebsiteStart(snapshot, report, handlers), el("ol", { className: "website-steps", attrs: { "aria-label": "How it works" } }, [
        ["01", "Enter your URL", "Start with a public website."], ["02", "Watch Victor work", "Your security agent, powered by Anthropic."], ["03", "Review clear fixes", "Practical steps, ready for your review."],
    ].map(([number, title, body]) => el("li", {}, [el("span", { className: "website-step-number" }, number), el("div", {}, [el("h2", {}, title), el("p", {}, body)])])))); }
    workspace.append(renderWebsiteHistory(snapshot, handlers));
    root.append(workspace);
}
