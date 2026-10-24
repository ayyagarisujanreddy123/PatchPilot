import { el } from "../util.js";
import { icon } from "../icons.js";
import { WEBSITE_ACTIVE_STATES, websiteTimestamp } from "../website.js";

function scene() {
    return el("div", { className: "website-scene", attrs: { "aria-hidden": "true" } }, [
        el("div", { className: "website-scene__base" }),
        el("div", { className: "website-scene__glass" }, [el("i"), el("i"), el("i")]),
        el("div", { className: "website-scene__shield" }, icon("shield")),
        el("span", { className: "website-scene__tag" }, "PHP"),
        el("span", { className: "website-scene__spark" }, icon("code")),
    ]);
}

export function renderWebsiteStart(snapshot, report, handlers) {
    const { ui, websiteExamples } = snapshot;
    const active = ui.websiteSubmitting || WEBSITE_ACTIVE_STATES.has(report?.state);
    const input = el("input", { id: "website-url", className: "registered-url__input", attrs: {
        type: "text", inputmode: "url", autocomplete: "url", spellcheck: "false", placeholder: "https://your-website.com", required: "required", maxlength: "2048",
        "aria-describedby": `website-url-help${ui.websiteError ? " website-url-error" : ""}`, "aria-invalid": ui.websiteError ? "true" : undefined,
    } });
    input.value = ui.websiteUrl;
    input.addEventListener("input", () => handlers.onUrlChange(input.value));
    const form = el("form", { className: "website-form", attrs: { "aria-label": "Assess a public website" } }, [
        el("label", { attrs: { for: "website-url" } }, "Your website URL"),
        el("div", { className: "registered-url__row" }, [el("div", { className: "website-input-wrap" }, [icon("globe"), input]),
            el("button", { className: "btn btn--primary", attrs: { type: "submit", id: "website-submit", disabled: active ? "disabled" : undefined } }, [ui.websiteSubmitting ? "Starting…" : active ? "Assessment in progress…" : "Assess website", active ? null : icon("arrow")])]),
        el("p", { className: "hint", id: "website-url-help" }, "Public HTTP(S) URL, without query parameters. We only read the public response."),
        ui.websiteError ? el("p", { id: "website-url-error", className: "field-error", attrs: { role: "alert" } }, ui.websiteError) : null,
    ]);
    form.addEventListener("submit", (event) => { event.preventDefault(); if (!active) { handlers.onSubmit(input.value); } });
    if (websiteExamples.length) {
        form.append(el("div", { className: "website-examples" }, [el("span", {}, "Just exploring?"), ...websiteExamples.map((example) => {
            const button = el("button", { className: "website-example-button", attrs: { type: "button", id: `website-example-${example.id}`, title: `${example.title} · fills the form without starting a scan` } }, ["Try the PHP demo", icon("arrow")]);
            button.addEventListener("click", () => handlers.onExample(example.url));
            return button;
        })]));
    }
    return el("section", { className: `website-start${report ? " website-start--compact" : ""}`, attrs: { "aria-label": "Start a website assessment" } }, [form, report ? null : scene(),
        report ? null : el("p", { className: "website-start__note" }, [icon("shield"), "Live evidence. Real AI analysis. Your review before any changes."])]);
}

export function renderWebsiteHistory(snapshot, handlers) {
    const { websiteHistory, websiteReports, ui } = snapshot;
    const root = el("details", { className: "website-history", id: "website-history" }, [
        el("summary", { id: "website-history-summary" }, [icon("clock"), `Recent assessments${websiteHistory.length ? ` · ${websiteHistory.length}` : ""}`]),
        el("div", { className: "website-history__body" }, [el("button", { className: "btn btn--ghost btn--small", attrs: { type: "button", id: "website-refresh" } }, "Refresh history"),
            websiteHistory.length ? el("ul", {}, websiteHistory.map((entry) => {
                const item = websiteReports[entry.assessmentId] ?? entry;
                const button = el("button", { attrs: { type: "button", id: `website-history-${item.assessmentId}`, "aria-current": item.assessmentId === ui.selectedAssessmentId ? "true" : undefined } }, [el("strong", {}, item.url), el("span", {}, `${item.state} · ${websiteTimestamp(item.createdAt)}`)]);
                button.addEventListener("click", () => handlers.onSelect(item.assessmentId));
                return el("li", {}, button);
            })) : el("p", { className: "muted" }, "Your assessments will appear here in this browser session.")]),
    ]);
    root.querySelector("#website-refresh").addEventListener("click", handlers.onRefresh);
    return root;
}
