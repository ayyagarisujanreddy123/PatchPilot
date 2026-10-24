/**
 * Owner-friendly approval drawer before a repair starts.
 */

import { clearElement, el } from "../util.js";
import { renderPlanSourceBadge } from "./badges.js";

const MITIGATION_NOTE =
    "session.upload_progress.enabled=0 is kept as a separate conservative mitigation (CVE-2026-115560).";
const AUTHORITY_NOTE =
    "PatchPilot only acts on this authorized, registered local site.";

function renderConfigList(configEntries) {
    if (!configEntries?.length) {
        return el("p", { className: "approval__muted" }, "—");
    }
    return el(
        "ul",
        { className: "approval__config-list" },
        configEntries.map((row) =>
            el("li", {}, `${row.key ?? "—"} = ${row.value ?? "—"}`),
        ),
    );
}

function renderChecklist(site, plan) {
    const items = [
        { label: "Homepage loads with your organization content", required: true },
        { label: "Contact form accepts valid input and rejects invalid input", required: true },
    ];
    if (site?.type === "upload") {
        items.push({
            label: "File upload accepts a real 3 MiB test file (byte count and hash verified)",
            required: true,
        });
    }
    return el(
        "ul",
        { className: "approval__checklist" },
        items.map((item) =>
            el("li", {}, [
                el("span", { attrs: { "aria-hidden": "true" } }, "☑ "),
                item.label,
            ]),
        ),
    );
}

export function renderApproval(root, snapshot, handlers) {
    clearElement(root);
    const { ui, sites, busy, advisory } = snapshot;
    const siteId = ui.approvalSiteId;
    if (!siteId) {
        root.hidden = true;
        root.removeAttribute("data-open");
        return;
    }
    root.hidden = false;
    root.dataset.open = "true";

    const site = sites.find((s) => s.id === siteId);
    const plan = ui.approvalPlan;
    const fixedVersion = advisory?.fixed_version ?? plan?.target_php_version ?? "8.3.36";
    const observedPhp = site?.php_version ?? "8.3.x";

    const finding =
        plan?.finding_plain ??
        `Your site runs PHP ${observedPhp}, which has a known critical issue. A fix (${fixedVersion}) is available.`;

    const overlay = el("button", {
        className: "drawer-overlay",
        attrs: { type: "button", "aria-label": "Close approval panel" },
    });
    overlay.addEventListener("click", handlers.closeApproval);

    const closeBtn = el(
        "button",
        {
            className: "drawer__close",
            attrs: { type: "button", "aria-label": "Cancel approval" },
        },
        "×",
    );
    closeBtn.addEventListener("click", handlers.closeApproval);

    const planBadge = plan?.plan_source ? renderPlanSourceBadge(plan.plan_source) : null;

    const approveDisabled = busy;
    const approveBtn = el(
        "button",
        {
            className: "btn btn--primary",
            attrs: {
                type: "button",
                id: "approval-approve-btn",
                disabled: approveDisabled ? "disabled" : undefined,
            },
        },
        "Approve repair",
    );
    if (!approveDisabled) {
        approveBtn.addEventListener("click", () => handlers.onApprove(siteId));
    }

    const cancelBtn = el(
        "button",
        { className: "btn btn--secondary", attrs: { type: "button" } },
        "Cancel",
    );
    cancelBtn.addEventListener("click", handlers.closeApproval);

    const drawer = el(
        "div",
        {
            className: "drawer",
            attrs: {
                role: "dialog",
                "aria-modal": "true",
                "aria-labelledby": "approval-title",
                "aria-describedby": "approval-finding",
            },
        },
        [
            el("header", { className: "drawer__header" }, [
                el("h2", { id: "approval-title", className: "drawer__title" }, "Review repair plan"),
                closeBtn,
            ]),
            el("div", { className: "drawer__body" }, [
                el("p", { className: "approval__org" }, site?.org_name ?? siteId),
                el("p", { id: "approval-finding", className: "approval__finding" }, finding),
                planBadge,
                el("h3", { className: "approval__section-title" }, "Proposed changes"),
                el("dl", { className: "approval__dl" }, [
                    el("div", {}, [el("dt", {}, "Target image"), el("dd", {}, plan?.target_image ?? "—")]),
                    el("div", {}, [
                        el("dt", {}, "Configuration profile"),
                        el("dd", {}, renderConfigList(plan?.config)),
                    ]),
                    el("div", {}, [el("dt", {}, "Why this plan"), el("dd", {}, plan?.rationale ?? "—")]),
                ]),
                el("h3", { className: "approval__section-title" }, "Website functions that must keep working"),
                renderChecklist(site, plan),
                el("p", { className: "approval__note" }, MITIGATION_NOTE),
                el("p", { className: "approval__note approval__note--authority" }, AUTHORITY_NOTE),
                busy
                    ? el("p", { className: "hint hint--disabled" }, "Repair actions are disabled while busy.")
                    : null,
            ].filter(Boolean)),
            el("footer", { className: "drawer__footer" }, [cancelBtn, approveBtn]),
        ],
    );

    root.append(overlay, drawer);

    requestAnimationFrame(() => {
        const focusTarget = drawer.querySelector("#approval-approve-btn:not([disabled])")
            ?? drawer.querySelector(".drawer__close");
        focusTarget?.focus();
    });
}

export function bindApprovalEscape(handler) {
    const onKey = (ev) => {
        if (ev.key === "Escape") {
            handler();
        }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
}
