/** Next useful action first; measured state and recorded evidence follow. */
import { clearElement, el } from "../util.js";
import { icon } from "../icons.js";
import { isRepairEligible } from "./badges.js";
import { renderReadiness } from "../components/readiness.js";
import { renderSites } from "./sites.js";

const attention = new Set(["vulnerable", "needs_help", "restoration_failed", "restored_unpatched", "candidate_rejected"]);

function summary(sites) {
    const values = [
        ["globe", "Registered sites", sites.length, "In this workspace"],
        ["shield", "Verified repairs", sites.filter((s) => s.status === "patched_verified").length, "Current deployments"],
        ["alert", "Need attention", sites.filter((s) => attention.has(s.status)).length, "Recorded findings or failures"],
        ["clock", "Awaiting assessment", sites.filter((s) => s.status === "unassessed").length, "Security status not yet checked"],
    ];
    return el("dl", { className: "workspace-stats", attrs: { "aria-label": "Current workspace summary" } }, values.map(([symbol, label, value, hint]) =>
        el("div", { className: "workspace-stat" }, [el("dt", {}, [icon(symbol), label]), el("dd", {}, [value, el("p", {}, hint)])])));
}

function assessmentForm({ ui, sites }, handlers, disabled) {
    const input = el("input", { className: "registered-url__input", id: "registered-site-url", attrs: {
        type: "text", inputmode: "url", placeholder: sites[0]?.address ?? "http://127.0.0.1:8081", required: "required",
        autocomplete: "url", spellcheck: "false", "aria-invalid": ui.urlError ? "true" : "false",
        "aria-describedby": `registered-url-help${ui.urlError ? " registered-url-error" : ""}`,
    } });
    input.value = ui.siteUrl ?? "";
    input.addEventListener("input", () => handlers.onUrlChange(input.value));
    const form = el("form", { className: "assessment-form" }, [
        el("label", { attrs: { for: "registered-site-url" } }, "Website URL"),
        el("div", { className: "registered-url__row" }, [input,
            el("button", { className: "btn btn--primary", attrs: { id: "assess-url", type: "submit", disabled: disabled ? "disabled" : undefined } }, "Assess site", icon("arrow"))]),
        el("p", { id: "registered-url-help", className: "hint" }, "Use a registered local URL below. Public sites need an authorized hosting connection."),
        ui.urlError ? el("p", { id: "registered-url-error", className: "field-error", attrs: { role: "alert" } }, [icon("info"), ui.urlError]) : null,
    ]);
    form.addEventListener("submit", (event) => { event.preventDefault(); handlers.onAssessUrl(input.value.trim()); });
    return el("section", { className: "assessment-panel", attrs: { "aria-labelledby": "assessment-title" } }, [
        el("div", { className: "assessment-panel__intro" }, [el("span", { className: "eyebrow" }, "Start with visibility"),
            el("h2", { id: "assessment-title" }, "A safer site starts with a clear assessment."),
            el("p", {}, "Check the serving PHP version and security configuration. Review the findings before you decide what changes."),
            el("span", { className: "assurance" }, [icon("shield"), "No repair without your approval"])]), form,
    ]);
}

function activity(events, handlers) {
    const view = el("button", { className: "text-action", attrs: { type: "button", id: "overview-view-activity" } }, "View activity", icon("arrow"));
    view.addEventListener("click", handlers.onViewActivity);
    const rows = [...events].slice(-3).reverse();
    return el("section", { className: "workspace-panel activity-preview" }, [
        el("div", { className: "section-heading" }, [el("h2", {}, "Recent run activity"), view]),
        rows.length ? el("ul", { className: "activity-preview__list" }, rows.map((event) => el("li", {}, [
            el("span", { className: "activity-dot", attrs: { "aria-hidden": "true" } }),
            el("div", {}, [el("p", {}, event.message), el("span", {}, event.site_id ?? "Workspace")])])))
            : el("p", { className: "muted empty-inline" }, "Your first assessment and repair will begin the activity trail."),
        rows.length ? el("p", { className: "hint" }, "History may include runs before the latest reset.") : null,
    ]);
}

export function renderFleet(root, snapshot, handlers) {
    clearElement(root);
    const { sites, ui, health, busy, events } = snapshot;
    const disabled = busy || ui.preparing || ui.resetting || !health?.ready || !health?.prepared;
    const eligible = sites.filter((site) => isRepairEligible(site.status)).map((site) => site.id);
    const filter = ui.siteFilter ?? "all";
    const visible = sites.filter((site) => filter === "all" || (filter === "verified" ? site.status === "patched_verified" : attention.has(site.status)));
    root.append(el("div", { className: "page-heading" }, [el("span", { className: "eyebrow" }, "Workspace / Overview"),
        el("h1", {}, "Your sites, one clear view."), el("p", {}, "Understand the risk. Approve the change. See the evidence.")]), renderReadiness(snapshot, handlers));
    if (ui.loading) {
        root.append(el("div", { className: "skeleton-grid", attrs: { role: "status", "aria-label": "Loading workspace" } }, [el("span", { className: "skeleton" }), el("span", { className: "skeleton" }), el("span", { className: "skeleton" })]));
        return;
    }
    root.append(summary(sites), assessmentForm(snapshot, handlers, disabled));
    const assessAll = el("button", { className: "btn btn--secondary btn--small", attrs: { type: "button", id: "assess-fleet", disabled: disabled || !eligible.length ? "disabled" : undefined } }, "Assess all sites", icon("arrow"));
    assessAll.addEventListener("click", () => handlers.startRepairAll(eligible));
    const filters = el("div", { className: "segmented-control", attrs: { "aria-label": "Filter registered sites" } }, [["all", "All sites"], ["attention", "Needs attention"], ["verified", "Verified"]].map(([value, label]) => {
        const button = el("button", { attrs: { id: `site-filter-${value}`, type: "button", "aria-pressed": filter === value ? "true" : "false" } }, label);
        button.addEventListener("click", () => handlers.onSiteFilter(value));
        return button;
    }));
    root.append(el("section", { className: "sites-section", attrs: { "aria-labelledby": "sites-heading" } }, [
        el("div", { className: "section-heading" }, [el("div", { className: "section-heading__title" }, [el("h2", { id: "sites-heading" }, "Registered sites"), el("span", { className: "count-badge" }, sites.length)]), assessAll]),
        filters, renderSites(visible, handlers, disabled),
    ]));
    const workflowItems = [["Assess", "Observe the actual PHP runtime and behavior."],
        ["Review & approve", "Choose the exact repair scope."], ["Stage & verify", "Test in isolation, then check the live site."]]
        .map(([title, description], index) => el("li", {}, [
            el("span", {}, index + 1), el("div", {}, [el("strong", {}, title), el("p", {}, description)]),
        ]));
    root.append(el("div", { className: "overview-bottom" }, [
        el("section", { className: "workspace-panel workflow-guide" }, [el("h2", {}, "A deliberate path to repair"), el("ol", {}, workflowItems)]),
        activity(events, handlers),
    ]));
    root.append(el("p", { className: "workspace-scope" }, [icon("info"), "This prototype checks a reviewed PHP runtime and configuration policy on registered local sites."]));
}
