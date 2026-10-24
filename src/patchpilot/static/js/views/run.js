/**
 * Per-site run detail: stepper, attempts, checks, outcome banner.
 */

import { WORKFLOW_STAGES } from "../mock.js";
import { clearElement, el, formatDuration } from "../util.js";
import { planSourceLabel, renderPlanSourceBadge, renderStatusBadge } from "./badges.js";

const CHECK_ORDER = [
    "serving_runtime",
    "homepage_contact",
    "upload_capability",
    "activation",
];

const CHECK_OWNER_LABELS = {
    serving_runtime: "Your site reports the expected PHP version and security settings",
    homepage_contact: "Homepage and contact form still work",
    upload_capability: "File upload accepts the required 3 MiB test file",
    activation: "Same checks pass again at your live web address",
};

const CHECK_TECH_LABELS = {
    serving_runtime: "Serving runtime",
    homepage_contact: "Homepage & contact",
    upload_capability: "Upload capability",
    activation: "Activation",
};

const STAGE_STATE_LABELS = {
    pending: "Pending",
    running: "Running",
    passed: "Passed",
    failed: "Failed",
    skipped: "Skipped",
};

function configToRows(config) {
    if (!config) {
        return [];
    }
    if (Array.isArray(config)) {
        return config.map((row) => [row.key, row.value]);
    }
    return Object.entries(config);
}

function renderConfigTable(config) {
    const rows = configToRows(config);
    if (!rows.length) {
        return el("p", { className: "run-muted" }, "—");
    }
    return el(
        "table",
        { className: "run-table run-table--compact" },
        el(
            "tbody",
            {},
            rows.map(([key, value]) => el("tr", {}, [el("th", { scope: "row" }, key), el("td", {}, value ?? "—")])),
        ),
    );
}

function computeConfigDiff(before, after) {
    const beforeMap = Object.fromEntries(configToRows(before));
    const afterMap = Object.fromEntries(configToRows(after));
    const keys = new Set([...Object.keys(beforeMap), ...Object.keys(afterMap)]);
    const diff = [];
    for (const key of keys) {
        const b = beforeMap[key];
        const a = afterMap[key];
        if (b !== a) {
            diff.push({ key, before: b ?? "—", after: a ?? "—" });
        }
    }
    return diff;
}

function renderConfigDiff(before, after) {
    const diff = computeConfigDiff(before, after);
    if (!diff.length) {
        return el("p", { className: "run-muted" }, "No configuration changes between attempts.");
    }
    const wrap = el("div", { className: "table-scroll" });
    wrap.append(
        el(
            "table",
            { className: "run-table" },
            [
                el(
                    "thead",
                    {},
                    el("tr", {}, [
                        el("th", { scope: "col" }, "Setting"),
                        el("th", { scope: "col" }, "Attempt 1"),
                        el("th", { scope: "col" }, "Attempt 2"),
                    ]),
                ),
                el(
                    "tbody",
                    {},
                    diff.map((row) =>
                        el("tr", {}, [
                            el("th", { scope: "row" }, row.key),
                            el("td", {}, row.before),
                            el("td", {}, row.after),
                        ]),
                    ),
                ),
            ],
        ),
    );
    return wrap;
}

function outcomeBannerMeta(run, site) {
    const outcome = run?.outcome;
    const status = site?.status;

    if (outcome === "patched_verified" || status === "patched_verified") {
        return {
            tone: "verified",
            title: "Patched & verified",
            body: "Final verification passed at your original site address.",
        };
    }
    if (outcome === "candidate_rejected" || status === "candidate_rejected") {
        return {
            tone: "warn",
            title: "Candidate rejected",
            body: "Staging candidate failed checks. Your original site kept serving.",
        };
    }
    if (outcome === "restored_unpatched" || status === "restored_unpatched") {
        return {
            tone: "warn",
            title: "Restored (still vulnerable / unpatched)",
            body: "The previous runtime was restored. This is not a successful patch.",
        };
    }
    if (outcome === "restoration_failed" || status === "restoration_failed") {
        return {
            tone: "danger",
            title: "Restoration failed",
            body: "PatchPilot could not restore the original site. Needs human help.",
        };
    }
    if (outcome === "needs_help" || status === "needs_help") {
        return {
            tone: "warn",
            title: "Needs human help",
            body: "Automated repair stopped. A person should review the evidence below.",
        };
    }
    if (run && !outcome) {
        return {
            tone: "progress",
            title: "Repair in progress",
            body: "Stages below show measured progress. No final outcome yet.",
        };
    }
    return null;
}

function renderOutcomeBanner(run, site) {
    const meta = outcomeBannerMeta(run, site);
    if (!meta) {
        return null;
    }
    return el(
        "div",
        {
            className: `outcome-banner outcome-banner--${meta.tone}`,
            attrs: { role: "status" },
        },
        [el("p", { className: "outcome-banner__title" }, meta.title), el("p", { className: "outcome-banner__body" }, meta.body)],
    );
}

function stageLabel(key) {
    return WORKFLOW_STAGES.find((s) => s.key === key)?.label ?? key;
}

function renderStepper(stages, ownerMode) {
    const list = stages?.length
        ? stages
        : WORKFLOW_STAGES.map((s) => ({ key: s.key, state: "pending", duration_ms: null }));

    return el(
        "ol",
        { className: "stepper", attrs: { "aria-label": "Repair workflow" } },
        list.map((stage) => {
            const state = stage.state ?? "pending";
            const label = ownerMode ? stageLabel(stage.key) : stage.key;
            return el(
                "li",
                {
                    className: `stepper__item stepper__item--${state}`,
                    attrs: { "aria-current": state === "running" ? "step" : undefined },
                },
                [
                    el("span", { className: "stepper__state", attrs: { "aria-hidden": "true" } }, STAGE_STATE_LABELS[state] ?? state),
                    el("span", { className: "stepper__label" }, label),
                    el("span", { className: "stepper__duration" }, formatDuration(stage.duration_ms)),
                ],
            );
        }),
    );
}

function renderPassFail(passed, ownerMode) {
    if (passed == null) {
        return el("span", { className: "check-pill check-pill--neutral" }, "—");
    }
    if (passed) {
        return el("span", { className: "check-pill check-pill--pass" }, [
            el("span", { attrs: { "aria-hidden": "true" } }, "✓ "),
            ownerMode ? "Passed" : "pass",
        ]);
    }
    return el("span", { className: "check-pill check-pill--fail" }, [
        el("span", { attrs: { "aria-hidden": "true" } }, "✕ "),
        ownerMode ? "Failed" : "fail",
    ]);
}

function renderChecksTable(checks, site, ownerMode, technicalDefaultOpen) {
    const byKey = Object.fromEntries((checks ?? []).map((c) => [c.key, c]));
    const isUpload = site?.type === "upload";
    const keys = CHECK_ORDER.filter((k) => isUpload || k !== "upload_capability");

    const rows = keys.map((key) => {
        const check = byKey[key];
        const label = ownerMode ? CHECK_OWNER_LABELS[key] : CHECK_TECH_LABELS[key];
        const expected = check?.expected ?? "—";
        const observed = check?.observed ?? "—";
        const evidenceId = `evidence-${key}-${check?.n ?? 1}`;
        const hasEvidence = Boolean(check?.evidence);

        const detail = el("div", { className: "check-detail", id: evidenceId, hidden: !technicalDefaultOpen && hasEvidence });
        if (hasEvidence) {
            detail.append(el("pre", { className: "check-detail__pre" }, check.evidence));
        } else {
            detail.append(el("p", { className: "run-muted" }, "No technical detail recorded."));
        }

        const toggle = hasEvidence
            ? el(
                  "button",
                  {
                      className: "link-button check-detail-toggle",
                      attrs: {
                          type: "button",
                          "aria-expanded": technicalDefaultOpen ? "true" : "false",
                          "aria-controls": evidenceId,
                      },
                  },
                  "Technical detail",
              )
            : null;

        if (toggle) {
            toggle.addEventListener("click", () => {
                const open = detail.hidden;
                detail.hidden = !open;
                toggle.setAttribute("aria-expanded", open ? "true" : "false");
            });
        }

        return el("tr", {}, [
            el("th", { scope: "row" }, label),
            el("td", {}, ownerMode ? expected : `expected: ${expected}`),
            el("td", {}, ownerMode ? observed : `observed: ${observed}`),
            el("td", {}, renderPassFail(check?.passed, ownerMode)),
            el("td", {}, toggle ?? "—"),
        ]);
    });

    const wrap = el("div", { className: "table-scroll" });
    wrap.append(
        el(
            "table",
            { className: "run-table" },
            [
                el(
                    "thead",
                    {},
                    el("tr", {}, [
                        el("th", { scope: "col" }, "Check"),
                        el("th", { scope: "col" }, "Expected"),
                        el("th", { scope: "col" }, "Observed"),
                        el("th", { scope: "col" }, "Result"),
                        el("th", { scope: "col" }, "Detail"),
                    ]),
                ),
                el("tbody", {}, rows),
            ],
        ),
    );
    return wrap;
}

function renderAttempt(attempt, site, ownerMode) {
    const badge = renderPlanSourceBadge(attempt.plan_source);
    const resultLabel = attempt.result ?? "In progress";
    return el("article", { className: "attempt-card" }, [
        el("header", { className: "attempt-card__header" }, [
            el("h3", { className: "attempt-card__title" }, `Attempt ${attempt.n ?? "—"}`),
            badge,
        ]),
        el("p", { className: "attempt-card__result" }, [
            el("span", { className: "attempt-card__result-label" }, "Result: "),
            resultLabel,
        ]),
        el("h4", { className: "attempt-card__subtitle" }, ownerMode ? "Settings in this attempt" : "config"),
        renderConfigTable(attempt.config),
        attempt.checks?.length
            ? el("h4", { className: "attempt-card__subtitle" }, "Verification checks (this attempt)")
            : null,
        attempt.checks?.length
            ? renderChecksTable(attempt.checks, site, ownerMode, !ownerMode)
            : null,
    ].filter(Boolean));
}

function isRecipeReuse(planSource) {
    const label = planSourceLabel(planSource);
    return label === "Verified recipe reuse";
}

export function renderRun(root, snapshot, handlers) {
    clearElement(root);
    const { ui, sites, runs } = snapshot;
    const siteId = ui.selectedSiteId;
    const site = sites.find((s) => s.id === siteId);
    const run = runs[siteId] ?? null;
    const ownerMode = ui.ownerMode !== false;
    const technicalDefaultOpen = !ownerMode;

    const back = el(
        "a",
        { className: "link-button run-back", attrs: { href: "#/fleet" } },
        "← Back to fleet",
    );
    back.addEventListener("click", (ev) => {
        ev.preventDefault();
        handlers.onBack();
    });

    root.append(
        back,
        el("h2", { className: "panel__title" }, site?.org_name ?? "Run detail"),
        site ? renderStatusBadge(site.status) : null,
    );

    const modeToggle = el("div", { className: "mode-toggle" }, [
        el("span", { id: "mode-toggle-label", className: "mode-toggle__label" }, "Detail level"),
        el(
            "button",
            {
                className: "btn btn--secondary",
                attrs: {
                    type: "button",
                    role: "switch",
                    "aria-checked": ownerMode ? "true" : "false",
                    "aria-labelledby": "mode-toggle-label",
                },
            },
            ownerMode ? "Plain language" : "Technical",
        ),
    ]);
    modeToggle.querySelector("button").addEventListener("click", handlers.onToggleMode);
    root.append(modeToggle);

    if (ui.runLoading && !run) {
        root.append(el("p", { className: "run-loading", attrs: { role: "status" } }, "Loading run record…"));
        return;
    }

    if (!run) {
        root.append(
            el("p", { className: "empty-state" }, "No run recorded for this site yet."),
            el("p", { className: "run-muted" }, "Start a repair from the fleet overview to create a run."),
        );
        return;
    }

    if (ui.runError) {
        root.append(el("p", { className: "hint hint--disabled", attrs: { role: "status" } }, ui.runError));
    }

    root.append(renderOutcomeBanner(run, site));

    const latestPlanSource = run.attempts?.[run.attempts.length - 1]?.plan_source ?? site?.plan_source;
    if (isRecipeReuse(latestPlanSource)) {
        root.append(
            el("p", { className: "run-note" }, "Recipe reused. Checks re-run on this site."),
        );
    }

    root.append(el("h3", { className: "run-section-title" }, "Workflow"));
    root.append(renderStepper(run.stages, ownerMode));

    if (run.rejections != null || run.rollbacks != null) {
        root.append(
            el("p", { className: "run-counts" }, [
                el("span", {}, `Staging rejections: ${run.rejections ?? "—"}`),
                " · ",
                el("span", {}, `Live rollbacks: ${run.rollbacks ?? "—"}`),
            ]),
        );
    }

    root.append(el("h3", { className: "run-section-title" }, "Attempts"));
    const attemptsWrap = el("div", { className: "attempts-list" });
    for (const attempt of run.attempts ?? []) {
        attemptsWrap.append(renderAttempt(attempt, site, ownerMode));
    }
    root.append(attemptsWrap);

    if ((run.attempts?.length ?? 0) >= 2) {
        root.append(el("h3", { className: "run-section-title" }, "Config changes (Attempt 1 → 2)"));
        root.append(renderConfigDiff(run.attempts[0].config, run.attempts[1].config));
    }

    const activeAttempt = run.attempts?.[run.attempts.length - 1];
    if (activeAttempt?.checks?.length) {
        root.append(el("h3", { className: "run-section-title" }, "Latest verification checks"));
        root.append(renderChecksTable(activeAttempt.checks, site, ownerMode, technicalDefaultOpen));
    }
}
