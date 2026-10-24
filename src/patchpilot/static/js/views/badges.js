/**
 * Status and plan provenance badges (icon + text; never color alone).
 */

import { el } from "../util.js";

const STATUS_MAP = {
    finalizing: { label: "Saving verification evidence", icon: "◐", tone: "progress" },
    unassessed: { label: "Ready for assessment", icon: "○", tone: "neutral" },
    queued: { label: "Queued", icon: "◐", tone: "progress" },
    planning: { label: "Choosing plan", icon: "◐", tone: "progress" },
    restoring: { label: "Restoring original", icon: "↩", tone: "progress" },
    vulnerable: {
        label: "Vulnerable",
        icon: "⚠",
        tone: "warn",
    },
    assessing: {
        label: "Assessing",
        icon: "◐",
        tone: "progress",
    },
    awaiting_approval: {
        label: "Awaiting approval",
        icon: "✋",
        tone: "progress",
    },
    staging: {
        label: "Staging candidate",
        icon: "◐",
        tone: "progress",
    },
    testing: {
        label: "Testing candidate",
        icon: "◐",
        tone: "progress",
    },
    candidate_rejected: {
        label: "Candidate rejected. Original site kept serving.",
        icon: "✕",
        tone: "warn",
    },
    revising: {
        label: "Revising plan",
        icon: "◐",
        tone: "progress",
    },
    activating: {
        label: "Activating",
        icon: "◐",
        tone: "progress",
    },
    rechecking: {
        label: "Rechecking live site",
        icon: "◐",
        tone: "progress",
    },
    patched_verified: {
        label: "Patched & verified",
        icon: "✓",
        tone: "verified",
    },
    restored_unpatched: {
        label: "Restored (still vulnerable / unpatched)",
        icon: "↩",
        tone: "warn",
    },
    restoration_failed: {
        label: "Restoration failed — needs human help",
        icon: "✕",
        tone: "danger",
    },
    needs_help: {
        label: "Needs human help",
        icon: "✕",
        tone: "warn",
    },
};

const PLAN_SOURCE_LABELS = {
    MODEL: "Fresh model plan",
    VERIFIED_RECIPE: "Verified recipe reuse",
    DETERMINISTIC_FALLBACK: "Deterministic fallback",
    SEEDED_DEMO: "Seeded demo candidate",
    TEST_DOUBLE: "Simulation — test double",
    fresh_model: "Fresh model plan",
    fresh_model_plan: "Fresh model plan",
    verified_recipe_reuse: "Verified recipe reuse",
    recipe_reuse: "Verified recipe reuse",
    seeded_fault: "Seeded fault candidate (demo)",
    seeded_fault_candidate: "Seeded fault candidate (demo)",
    deterministic_fallback: "Deterministic fallback (labeled)",
    fallback: "Deterministic fallback (labeled)",
};

export function statusMeta(status) {
    if (status == null || status === "") {
        return { label: "Unknown status", icon: "?", tone: "neutral" };
    }
    return STATUS_MAP[status] ?? { label: "Unknown status", icon: "?", tone: "neutral" };
}

export function planSourceLabel(planSource) {
    if (planSource == null || planSource === "") {
        return null;
    }
    if (PLAN_SOURCE_LABELS[planSource]) {
        return PLAN_SOURCE_LABELS[planSource];
    }
    if (Object.values(PLAN_SOURCE_LABELS).includes(planSource)) {
        return planSource;
    }
    return String(planSource);
}

export function renderStatusBadge(status) {
    const meta = statusMeta(status);
    return el(
        "span",
        {
            className: `badge badge--${meta.tone}`,
            attrs: { role: "status" },
        },
        [
            el("span", { className: "badge__icon", attrs: { "aria-hidden": "true" } }, meta.icon),
            el("span", { className: "badge__text" }, meta.label),
        ],
    );
}

export function renderPlanSourceBadge(planSource) {
    const label = planSourceLabel(planSource);
    if (!label) {
        return null;
    }
    return el(
        "span",
        {
            className: "badge badge--plan",
            attrs: { role: "status" },
        },
        [
            el("span", { className: "badge__icon", attrs: { "aria-hidden": "true" } }, "◎"),
            el("span", { className: "badge__text" }, label),
        ],
    );
}

export function isRepairEligible(status) {
    return ["unassessed", "vulnerable", "awaiting_approval", "restored_unpatched", "candidate_rejected", "needs_help"].includes(status);
}

export function formatChecks(passed, required) {
    if (passed == null && required == null) {
        return "—";
    }
    const p = passed == null ? "—" : String(passed);
    const r = required == null ? "—" : String(required);
    return `${p}/${r}`;
}

export function siteTypeLabel(type) {
    if (type === "upload") {
        return "Upload";
    }
    if (type === "basic") {
        return "Basic";
    }
    return type ?? "—";
}
