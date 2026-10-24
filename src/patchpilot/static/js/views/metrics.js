/**
 * Metrics & evidence panel — measured values only.
 */

import { clearElement, el, formatDuration } from "../util.js";
import { planSourceLabel } from "./badges.js";

function metricValue(value) {
    return value == null ? "—" : String(value);
}

function renderMetricRow(label, value) {
    return el("div", { className: "metrics-grid__row" }, [
        el("span", { className: "metrics-grid__label" }, label),
        el("span", { className: "metrics-grid__value" }, metricValue(value)),
    ]);
}

function renderSummarySection(metrics) {
    const m = metrics ?? {};
    const items = [
        {
            label: "Sites patched",
            value: `${metricValue(m.sites_patched)}/${metricValue(m.sites_total)}`,
        },
        { label: "Sites needing help", value: m.sites_needing_help },
        { label: "Staging rejections", value: m.rejections },
        { label: "Live rollbacks", value: m.rollbacks },
    ];
    return el(
        "section",
        { className: "metrics-section", attrs: { "aria-labelledby": "metrics-outcomes-heading" } },
        [
            el("h3", { className: "metrics-section__title", id: "metrics-outcomes-heading" }, "Fleet outcomes"),
            el(
                "div",
                { className: "summary-bar", attrs: { "aria-label": "Fleet outcome metrics" } },
                items.map((item) =>
                    el("div", { className: "summary-bar__item" }, [
                        el("span", { className: "summary-bar__label" }, item.label),
                        el("span", { className: "summary-bar__value" }, metricValue(item.value)),
                    ]),
                ),
            ),
        ],
    );
}

function renderPlanSourcesTable(planSources) {
    const entries = planSources && typeof planSources === "object" ? Object.entries(planSources) : [];
    if (!entries.length) {
        return el("p", { className: "run-muted" }, "No plan source counts reported yet.");
    }
    const rows = entries.map(([key, count]) =>
        el("tr", {}, [
            el("th", { scope: "row" }, planSourceLabel(key) ?? key),
            el("td", {}, metricValue(count)),
        ]),
    );
    return el(
        "div",
        { className: "table-scroll" },
        el(
            "table",
            { className: "run-table run-table--compact" },
            el("tbody", {}, rows),
        ),
    );
}

function renderPlanningSection(metrics) {
    const m = metrics ?? {};
    const checksDisplay =
        m.checks_passed == null && m.checks_required == null
            ? "—"
            : `${metricValue(m.checks_passed)}/${metricValue(m.checks_required)}`;

    const rows = [
        renderMetricRow("Recipe hits", m.recipe_hits),
        renderMetricRow("Planner invocations", m.planner_invocations),
    ];
    if (m.model_requests != null) {
        rows.push(renderMetricRow("Model requests", m.model_requests));
    }
    rows.push(
        renderMetricRow("Attempts (total)", m.attempts_total),
        renderMetricRow("Checks passed / required", checksDisplay),
    );

    return el(
        "section",
        { className: "metrics-section", attrs: { "aria-labelledby": "metrics-planning-heading" } },
        [
            el("h3", { className: "metrics-section__title", id: "metrics-planning-heading" }, "Planning & checks"),
            el("h4", { className: "metrics-subtitle" }, "Plan sources"),
            renderPlanSourcesTable(m.plan_sources),
            el("div", { className: "metrics-grid metrics-grid--stack" }, rows),
        ],
    );
}

const PHASE_LABELS = {
    planning: "Planning",
    staging: "Staging",
    testing: "Testing",
    activation: "Activation",
    total: "Total",
};

function renderPhaseDurations(phaseDurations) {
    const phases = phaseDurations && typeof phaseDurations === "object" ? phaseDurations : {};
    const keys = ["planning", "staging", "testing", "activation", "total"];
    const values = keys.map((k) => phases[k]).filter((v) => v != null && !Number.isNaN(Number(v)));
    const max = values.length ? Math.max(...values.map(Number)) : 0;

    const rows = keys.map((key) => {
        const ms = phases[key];
        const label = PHASE_LABELS[key] ?? key;
        const durationText = formatDuration(ms);
        let barFill = null;
        if (ms != null && max > 0) {
            const pct = Math.min(100, Math.round((Number(ms) / max) * 100));
            barFill = el("div", {
                className: "metrics-bar__fill",
                attrs: {
                    style: `width: ${pct}%`,
                    role: "presentation",
                },
            });
        }
        return el("tr", {}, [
            el("th", { scope: "row" }, label),
            el("td", {}, [
                el("span", { className: "metrics-bar__label" }, durationText),
                ms != null && max > 0
                    ? el("div", { className: "metrics-bar", attrs: { "aria-hidden": "true" } }, barFill)
                    : null,
            ]),
        ]);
    });

    return el(
        "div",
        { className: "table-scroll" },
        el("table", { className: "run-table" }, el("tbody", {}, rows)),
    );
}

function renderDurationsSection(metrics) {
    const phases = metrics?.phase_durations_ms ?? metrics?.durations_ms ?? null;
    return el(
        "section",
        { className: "metrics-section", attrs: { "aria-labelledby": "metrics-durations-heading" } },
        [
            el("h3", { className: "metrics-section__title", id: "metrics-durations-heading" }, "Phase durations"),
            renderPhaseDurations(phases),
        ],
    );
}

function flattenComparisonValues(obj, prefix = "") {
    if (obj == null || typeof obj !== "object" || Array.isArray(obj)) {
        return [[prefix || "value", obj]];
    }
    const rows = [];
    for (const [key, value] of Object.entries(obj)) {
        const path = prefix ? `${prefix}.${key}` : key;
        if (value != null && typeof value === "object" && !Array.isArray(value)) {
            rows.push(...flattenComparisonValues(value, path));
        } else {
            rows.push([path, value]);
        }
    }
    return rows;
}

function renderComparisonArm(title, data) {
    const rows = flattenComparisonValues(data);
    if (!rows.length) {
        return el("div", { className: "metrics-compare__arm" }, [
            el("h4", { className: "metrics-compare__arm-title" }, title),
            el("p", { className: "run-muted" }, "—"),
        ]);
    }
    return el("div", { className: "metrics-compare__arm" }, [
        el("h4", { className: "metrics-compare__arm-title" }, title),
        el(
            "div",
            { className: "table-scroll" },
            el(
                "table",
                { className: "run-table run-table--compact" },
                el(
                    "tbody",
                    {},
                    rows.map(([key, value]) =>
                        el("tr", {}, [
                            el("th", { scope: "row" }, key),
                            el("td", {}, metricValue(value)),
                        ]),
                    ),
                ),
            ),
        ),
    ]);
}

function renderMemoryComparison(comparison) {
    if (comparison == null || typeof comparison !== "object") {
        return el(
            "section",
            { className: "metrics-section", attrs: { "aria-labelledby": "metrics-memory-heading" } },
            [
                el("h3", { className: "metrics-section__title", id: "metrics-memory-heading" }, "Memory comparison"),
                el("p", { className: "run-muted" }, "Not measured in this run."),
            ],
        );
    }

    const arms = [];
    if ("with_memory" in comparison || "without_memory" in comparison) {
        if (comparison.without_memory != null) {
            arms.push(renderComparisonArm("Memory disabled", comparison.without_memory));
        }
        if (comparison.with_memory != null) {
            arms.push(renderComparisonArm("Memory enabled", comparison.with_memory));
        }
    } else {
        const entries = Object.entries(comparison);
        for (const [key, value] of entries) {
            const title = key.replace(/_/g, " ");
            arms.push(renderComparisonArm(title, value));
        }
    }

    return el(
        "section",
        { className: "metrics-section", attrs: { "aria-labelledby": "metrics-memory-heading" } },
        [
            el("h3", { className: "metrics-section__title", id: "metrics-memory-heading" }, "Memory comparison"),
            el(
                "p",
                { className: "metrics-honesty-caption" },
                "Small comparison. Does not establish a universal speedup.",
            ),
            el("div", { className: "metrics-compare" }, arms),
        ],
    );
}

export function renderMetrics(root, snapshot) {
    clearElement(root);
    const { metrics, ui } = snapshot;

    root.append(el("h1", { className: "panel__title" }, "Demo insights"));
    root.append(
        el(
            "p",
            { className: "panel__lede" },
            ["MOCK", "SIMULATION"].includes(snapshot.health?.mode)
                ? "Simulated demonstration values. These are not measurements of running websites."
                : "Measured values from completed and in-progress runs. Missing fields are not estimated.",
        ),
    );

    if (ui.loading) {
        root.append(el("p", { className: "panel__status", attrs: { role: "status" } }, "Loading metrics…"));
        return;
    }

    if (metrics == null) {
        root.append(el("p", { className: "empty-state" }, "Aggregate metrics are not exposed by this API. Open a run to inspect its recorded checks, security results, recovery, and planning provenance."));
        return;
    }

    root.append(renderSummarySection(metrics));
    root.append(renderPlanningSection(metrics));
    root.append(renderDurationsSection(metrics));
    root.append(renderMemoryComparison(metrics.memory_comparison));
}
