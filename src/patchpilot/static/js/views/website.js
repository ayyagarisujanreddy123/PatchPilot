import { clearElement, el } from "../util.js";
import { WEBSITE_ACTIVE_STATES, websiteTimestamp } from "../website.js";
import { evidenceLinks, renderWebsiteEvidence, sourceLink } from "./websiteEvidence.js";
import { renderWebsiteFindings, renderWebsiteAnalysis } from "./websiteFindings.js";

function progress(report) {
    const stages = ["QUEUED", "COLLECTING", "ANALYZING", "COMPLETED"];
    const labels = { QUEUED: "Queued", COLLECTING: "Collecting HTTP evidence", ANALYZING: "Analyzing observations", COMPLETED: "Assessment completed", FAILED: "Assessment stopped" };
    const activity = (events) => el("ol", { className: "website-event-list", attrs: { "aria-label": "Recorded assessment activity" } }, events.map((event) => el("li", {}, [el("time", { attrs: { datetime: event.timestamp } }, websiteTimestamp(event.timestamp)), el("strong", {}, event.stage === "ANALYZING" ? "Anthropic agent" : event.stage === "COLLECTING" ? "HTTP collection" : event.stage), el("span", {}, event.message)])));
    return el("section", { className: "website-progress", attrs: { "aria-labelledby": "website-progress-heading" } }, [
        el("div", { className: "section-heading" }, [el("h3", { id: "website-progress-heading" }, labels[report.state] ?? report.state), el("span", { className: `website-state website-state--${report.state.toLowerCase()}` }, report.state)]),
        el("div", { className: "website-agent-status" }, [
            WEBSITE_ACTIVE_STATES.has(report.state) ? el("span", { className: "website-spinner", attrs: { "aria-hidden": "true" } }) : null,
            el("div", {}, [el("strong", {}, report.state === "ANALYZING" ? "Anthropic agent is working" : report.state === "COLLECTING" ? "Collecting public HTTP responses" : report.state === "QUEUED" ? "Waiting for assessment worker" : report.state === "COMPLETED" ? "Collection and analysis recorded" : "Assessment stopped"),
                el("p", { id: "website-agent-message", attrs: { role: "status" } }, report.stageMessage)]),
        ]),
        report.events.length ? el("p", { className: "muted" }, `Last recorded update: ${websiteTimestamp(report.events.at(-1).timestamp)}`) : null,
        el("ol", { className: "website-stages" }, stages.map((stage) => el("li", { className: stage === report.state ? "is-current" : stages.indexOf(stage) < stages.indexOf(report.state) ? "is-complete" : "", attrs: { "aria-current": stage === report.state ? "step" : undefined } }, labels[stage]))),
        report.error ? el("p", { className: "field-error", attrs: { role: "alert" } }, report.error) : null,
        el("p", { className: "muted" }, report.state === "COMPLETED" ? "Assessment completed describes the collected responses and analysis. It is not a verified repair or a declaration that the website is safe." : report.state === "FAILED" ? "Partial observations are retained below. No precomputed result or simulated evidence has been substituted." : "Fresh observations and provider analysis will appear as the job progresses."),
        el("h4", {}, "Live agent activity"), activity(report.events.slice(-8)),
        report.events.length > 8 ? el("details", { id: `website-progress-events-${report.assessmentId}` }, [el("summary", { id: `website-progress-events-summary-${report.assessmentId}` }, "Earlier assessment activity"), activity(report.events.slice(0, -8))]) : null,
    ]);
}

function reportView(report, handlers) {
    const detection = report.phpDetection;
    const root = el("section", { className: "website-report", attrs: { "aria-labelledby": "website-report-heading" } }, [
        el("div", { className: "section-heading" }, [el("div", {}, [el("p", { className: "eyebrow" }, "RECORDED WEBSITE ASSESSMENT"), el("h3", { id: "website-report-heading" }, sourceLink(report.url))]),
            el("button", { className: "btn btn--secondary btn--small", attrs: { type: "button", id: "website-rescan", disabled: WEBSITE_ACTIVE_STATES.has(report.state) ? "disabled" : undefined } }, "Assess this URL again")]),
        el("p", { className: "website-report-meta" }, `Created ${websiteTimestamp(report.createdAt)}${report.finishedAt ? ` · Finished ${websiteTimestamp(report.finishedAt)}` : ""} · ${report.assessmentId}`),
        progress(report),
        el("section", { className: "website-php", attrs: { "aria-labelledby": "website-php-heading" } }, [
            el("div", { className: "website-finding-heading" }, [el("h3", { id: "website-php-heading" }, detection.status === "UNKNOWN" ? "PHP version unknown" : detection.version ? `PHP ${detection.version}` : "PHP signal detected"), el("span", { className: "chip" }, detection.status === "REPORTED" ? "Reported by public response" : detection.status === "INFERRED" ? "Inferred signal" : "Unknown")]),
            el("p", {}, detection.explanation),
            el("p", { className: "muted" }, "Public banners and PHP links do not establish an installed package's patch or backport status."),
            evidenceLinks(detection.evidenceIds, report, "php"),
        ]),
        renderWebsiteFindings(report), renderWebsiteEvidence(report), renderWebsiteAnalysis(report),
        el("section", { className: "website-section website-coverage" }, [el("h3", {}, "Coverage & limitations"),
            el("h4", {}, "What this assessment covered"), el("ul", {}, report.coverage.map((item) => el("li", {}, item))),
            el("h4", {}, "What remains uncertain"), el("ul", {}, report.limitations.map((item) => el("li", {}, item))),
        ]),
    ]);
    root.querySelector("#website-rescan").addEventListener("click", () => handlers.onSubmit(report.url));
    return root;
}

export function renderWebsite(root, snapshot, handlers) {
    clearElement(root);
    const { ui, websiteHistory, websiteExamples, websiteReports } = snapshot;
    const report = websiteReports[ui.selectedAssessmentId] ?? null;
    const active = ui.websiteSubmitting || WEBSITE_ACTIVE_STATES.has(report?.state);
    root.append(el("div", { className: "page-heading" }, [el("div", {}, [el("p", { className: "eyebrow" }, "LIVE PUBLIC HTTP OBSERVATIONS"), el("h1", { className: "panel__title" }, "Website assessment"), el("p", { className: "panel__lede" }, "Enter a public website URL to collect fresh response evidence and get Anthropic remediation guidance.")]) ]));
    const input = el("input", { id: "website-url", className: "registered-url__input", attrs: { type: "text", inputmode: "url", autocomplete: "url", spellcheck: "false", placeholder: "http://php.testsparker.com/", required: "required", maxlength: "2048", "aria-describedby": `website-url-help${ui.websiteError ? " website-url-error" : ""}`, "aria-invalid": ui.websiteError ? "true" : undefined } });
    input.value = ui.websiteUrl;
    input.addEventListener("input", () => handlers.onUrlChange(input.value));
    const form = el("form", { className: "website-form", attrs: { "aria-label": "Assess a public website" } }, [
        el("label", { attrs: { for: "website-url" } }, "Public website URL"),
        el("div", { className: "registered-url__row" }, [input, el("button", { className: "btn btn--primary", attrs: { type: "submit", id: "website-submit", disabled: active ? "disabled" : undefined } }, ui.websiteSubmitting ? "Starting assessment…" : active ? "Assessment in progress…" : "Assess website")]),
        el("p", { className: "hint", id: "website-url-help" }, "Public HTTP(S), ports 80/443, without query parameters. Read-only GET requests; suggested fixes require your review and access to the server."),
        ui.websiteError ? el("p", { id: "website-url-error", className: "field-error", attrs: { role: "alert" } }, ui.websiteError) : null,
    ]);
    form.addEventListener("submit", (event) => { event.preventDefault(); if (!active) { handlers.onSubmit(input.value); } });
    if (websiteExamples.length) {
        form.append(el("p", { className: "website-example-label" }, "Public sample URLs · fills the form; results are collected only when you start"),
            el("div", { className: "website-examples" }, websiteExamples.map((example) => {
                const button = el("button", { className: "btn btn--small btn--secondary", attrs: { type: "button", id: `website-example-${example.id}`, title: example.description } }, example.title);
                button.addEventListener("click", () => handlers.onExample(example.url));
                return button;
            })));
    }
    root.append(form);
    if (ui.websiteConnectionError) { root.append(el("p", { className: "field-error", attrs: { role: "alert" } }, ui.websiteConnectionError)); }
    if (ui.websiteLoading && !report) { root.append(el("p", { attrs: { role: "status" } }, "Loading this session's assessment records…")); }
    if (report) { root.append(reportView(report, handlers)); }
    root.append(el("section", { className: "website-section website-history" }, [
        el("div", { className: "section-heading" }, [el("h3", {}, "Recent assessments"), el("button", { className: "btn btn--small btn--secondary", attrs: { type: "button", id: "website-refresh" } }, "Refresh history")]),
        websiteHistory.length ? el("ul", {}, websiteHistory.map((entry) => {
            const item = websiteReports[entry.assessmentId] ?? entry;
            const button = el("button", { attrs: { type: "button", id: `website-history-${item.assessmentId}`, "aria-current": item.assessmentId === ui.selectedAssessmentId ? "true" : undefined } }, [el("strong", {}, item.url), el("span", {}, `${item.state} · ${websiteTimestamp(item.createdAt)}`)]);
            button.addEventListener("click", () => handlers.onSelect(item.assessmentId));
            return el("li", {}, button);
        })) : el("p", { className: "muted" }, "Assessments created in this browser session will appear here."),
    ]));
    root.querySelector("#website-refresh").addEventListener("click", handlers.onRefresh);
}
