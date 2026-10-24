import { el } from "../util.js";
import { icon } from "../icons.js";
import { WEBSITE_ACTIVE_STATES, websiteTimestamp } from "../website.js";

function activity(report) {
    return el("ol", { className: "website-event-list", attrs: { "aria-label": "Recorded assessment activity" } }, report.events.map((event) => el("li", {}, [
        el("time", { attrs: { datetime: event.timestamp } }, websiteTimestamp(event.timestamp)),
        el("strong", {}, event.stage === "ANALYZING" ? "Victor" : event.stage === "COLLECTING" ? "HTTP collection" : event.stage),
        el("span", {}, event.message),
    ])));
}

export function renderWebsiteProgress(report) {
    const active = WEBSITE_ACTIVE_STATES.has(report.state);
    const failed = report.state === "FAILED";
    const stages = ["COLLECTING", "ANALYZING", "COMPLETED"];
    const current = report.state === "QUEUED" ? 0 : stages.indexOf(report.state);
    const labels = ["Collect evidence", "Analyze with AI", "Review fixes"];
    const log = el("details", { className: "website-disclosure", id: `website-progress-events-${report.assessmentId}` }, [
        el("summary", { id: `website-progress-events-summary-${report.assessmentId}` }, `Live agent activity · ${report.events.length} recorded updates`), activity(report),
    ]);
    if (!active && !failed) {
        return el("div", { className: "website-completed-activity" }, [
            el("p", { id: "website-agent-message", className: "visually-hidden", attrs: { role: "status" } }, report.stageMessage), log,
        ]);
    }
    return el("section", { className: `website-progress ${failed ? "website-progress--failed" : "website-progress--active"}`, attrs: { "aria-labelledby": "website-progress-heading" } }, [
        el("div", { className: "website-agent-status" }, [
            active ? el("span", { className: "website-spinner", attrs: { "aria-hidden": "true" } }) : icon("alert"),
            el("div", {}, [el("h2", { id: "website-progress-heading" }, failed ? "We couldn't finish this assessment" : report.state === "ANALYZING" ? "Victor is working" : "Checking your website"),
                el("p", { id: "website-agent-message", attrs: { role: failed ? "alert" : "status" } }, report.stageMessage)]),
        ]),
        active ? el("ol", { className: "website-stages", attrs: { "aria-label": "Assessment progress" } }, stages.map((stage, index) => el("li", {
            className: index === current ? "is-current" : index < current ? "is-complete" : "",
            attrs: { "aria-current": index === current ? "step" : undefined },
        }, [el("span", { className: "website-stage-number", attrs: { "aria-hidden": "true" } }, index < current ? icon("check") : String(index + 1)), labels[index]]))) : null,
        failed ? el("p", { className: "muted" }, "Any collected findings are available below. You can retry this URL.") : null,
        log,
    ]);
}
