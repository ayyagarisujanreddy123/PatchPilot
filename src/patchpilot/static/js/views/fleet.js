/**
 * Fleet overview: summary bar, site cards, repair actions.
 */

import { clearElement, el } from "../util.js";
import {
    formatChecks,
    isRepairEligible,
    renderPlanSourceBadge,
    renderStatusBadge,
    siteTypeLabel,
} from "./badges.js";

const BUSY_REASON = "Another repair or reset is in progress.";

function siteCardAccentClass(status) {
    if (!status) {
        return "site-card--neutral";
    }
    if (status === "vulnerable" || status === "restored_unpatched") {
        return "site-card--vulnerable";
    }
    if (status === "patched_verified") {
        return "site-card--verified";
    }
    if (["restoration_failed", "needs_help", "candidate_rejected"].includes(status)) {
        return "site-card--danger";
    }
    const active = new Set([
        "assessing",
        "awaiting_approval",
        "staging",
        "testing",
        "revising",
        "activating",
        "rechecking",
    ]);
    if (active.has(status)) {
        return "site-card--progress";
    }
    return "site-card--neutral";
}

function metricValue(value) {
    return value == null ? "—" : String(value);
}

function renderSummaryBar(metrics) {
    const m = metrics ?? {};
    const items = [
        { label: "Sites patched", value: `${metricValue(m.sites_patched)}/${metricValue(m.sites_total)}` },
        { label: "Needing help", value: metricValue(m.sites_needing_help) },
        { label: "Staging rejections", value: metricValue(m.rejections) },
        { label: "Live rollbacks", value: metricValue(m.rollbacks) },
    ];
    return el(
        "div",
        { className: "summary-bar", attrs: { "aria-label": "Fleet summary" } },
        items.map((item) =>
            el("div", { className: "summary-bar__item" }, [
                el("span", { className: "summary-bar__label" }, item.label),
                el("span", { className: "summary-bar__value" }, item.value),
            ]),
        ),
    );
}

function renderSiteCard(site, handlers, { busy, disabledReason }) {
    const planBadge = renderPlanSourceBadge(site.plan_source);
    const statusBadge = renderStatusBadge(site.status);
    const canRepair = !busy && isRepairEligible(site.status);
    const repairDisabled = !canRepair;
    const repairReason = busy ? disabledReason : null;

    const repairBtn = el(
        "button",
        {
            className: "btn btn--primary",
            attrs: {
                type: "button",
                disabled: repairDisabled ? "disabled" : undefined,
                "aria-disabled": repairDisabled ? "true" : "false",
            },
        },
        "Approve & repair",
    );
    if (canRepair) {
        repairBtn.addEventListener("click", () => handlers.openApproval(site.id));
    }

    const viewRun = el(
        "a",
        {
            className: "btn btn--ghost",
            attrs: { href: `#/run/${site.id}` },
        },
        "View run",
    );
    viewRun.addEventListener("click", (ev) => {
        ev.preventDefault();
        handlers.viewRun(site.id);
    });

    const disabledNote =
        repairReason && repairDisabled
            ? el("p", { className: "hint hint--disabled" }, repairReason)
            : null;

    return el(
        "article",
        {
            className: `site-card ${siteCardAccentClass(site.status)}`,
            attrs: { "aria-labelledby": `site-title-${site.id}` },
        },
        [
            el("header", { className: "site-card__header" }, [
                el("h3", { className: "site-card__title", id: `site-title-${site.id}` }, site.org_name ?? "—"),
                el("span", { className: "site-card__type" }, siteTypeLabel(site.type)),
            ]),
            el("dl", { className: "site-card__meta" }, [
                el("div", { className: "site-card__row" }, [
                    el("dt", {}, "Address"),
                    el("dd", {}, site.address ?? "—"),
                ]),
                el("div", { className: "site-card__row" }, [
                    el("dt", {}, "PHP / SAPI"),
                    el("dd", {}, `${site.php_version ?? "—"} · ${site.sapi ?? "—"}`),
                ]),
                el("div", { className: "site-card__row" }, [
                    el("dt", {}, "Checks passed"),
                    el("dd", {}, formatChecks(site.checks_passed, site.checks_required)),
                ]),
                el("div", { className: "site-card__row" }, [
                    el("dt", {}, "Attempts"),
                    el("dd", {}, site.attempts == null ? "—" : String(site.attempts)),
                ]),
            ]),
            el("div", { className: "site-card__badges" }, [statusBadge, planBadge].filter(Boolean)),
            el("div", { className: "site-card__actions" }, [repairBtn, viewRun]),
            disabledNote,
        ].filter(Boolean),
    );
}

export function renderFleet(root, snapshot, handlers) {
    clearElement(root);
    const { sites, metrics, busy, ui } = snapshot;
    const disabledReason = BUSY_REASON;

    root.append(el("h2", { className: "panel__title" }, "Fleet overview"));
    root.append(renderSummaryBar(metrics));

    const eligibleIds = sites.filter((s) => isRepairEligible(s.status)).map((s) => s.id);
    const repairAllDisabled = busy || eligibleIds.length === 0;

    const repairAllBtn = el(
        "button",
        {
            className: "btn btn--primary btn--wide",
            attrs: {
                type: "button",
                disabled: repairAllDisabled ? "disabled" : undefined,
            },
        },
        "Approve & repair all",
    );
    if (!repairAllDisabled) {
        repairAllBtn.addEventListener("click", () => handlers.startRepairAll(eligibleIds));
    }

    const toolbar = el("div", { className: "fleet-toolbar" }, repairAllBtn);
    if (busy) {
        toolbar.append(el("p", { className: "hint hint--disabled" }, disabledReason));
    } else if (eligibleIds.length === 0) {
        toolbar.append(
            el("p", { className: "hint" }, "No vulnerable sites waiting for repair."),
        );
    }
    root.append(toolbar);

    if (ui.loading) {
        root.append(el("p", { className: "panel__lede", attrs: { role: "status" } }, "Loading fleet…"));
        return;
    }

    if (!sites.length) {
        root.append(el("p", { className: "empty-state" }, "No registered sites yet."));
        return;
    }

    const grid = el(
        "div",
        { className: "site-grid", attrs: { role: "list" } },
        sites.map((site) =>
            el("div", { className: "site-grid__cell", attrs: { role: "listitem" } }, [
                renderSiteCard(site, handlers, { busy, disabledReason }),
            ]),
        ),
    );
    root.append(grid);
}
