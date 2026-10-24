/** Review actual assessment scope before creating an approval. */
import { clearElement, el } from "../util.js";
import { renderPlanSourceBadge } from "./badges.js";

const checkNames = {
    runtime_version: "PHP version", sapi: "HTTP serving mode",
    upload_progress: "Upload-session mitigation", deployment_identity: "Tested deployment identity",
    homepage: "Homepage content", contact_valid: "Contact form accepts valid input",
    contact_invalid: "Contact form rejects invalid input", upload_size: "3 MiB upload byte count",
    upload_hash: "3 MiB upload SHA-256",
};

function formatValue(value) {
    return typeof value === "string" ? value : JSON.stringify(value, null, 2);
}

function renderAssessment(assessment, sites) {
    const site = sites.find((item) => item.id === assessment.siteId);
    const runtime = assessment.currentRuntime ?? {};
    const mitigation = runtime.uploadProgressEnabled;
    const mitigationSummary = mitigation === false || mitigation === 0 || mitigation === "0"
        ? "upload progress disabled" : mitigation === true || mitigation === 1 || mitigation === "1"
            ? "upload progress enabled" : "upload progress setting not recorded";
    return el("section", { className: "evidence-section" }, [
        el("h3", {}, site?.org_name ?? assessment.siteId),
        el("p", {}, `${site?.address ?? assessment.siteId} · ${assessment.applicability}`),
        el("h4", {}, "Observed serving runtime"),
        el("p", {}, `PHP ${runtime.phpVersion ?? "not recorded"} · ${runtime.sapi ?? "SAPI not recorded"} · ${mitigationSummary}`),
        el("details", { id: `assessment-runtime-${assessment.siteId}` }, [
            el("summary", { id: `assessment-runtime-summary-${assessment.siteId}` }, "Technical runtime evidence"),
            el("pre", {}, formatValue(runtime)),
        ]),
        el("h4", {}, "Proposed changes"),
        el("ul", {}, (assessment.proposedChanges ?? []).map((change) => el("li", {}, formatValue(change)))),
        el("h4", {}, "Required verification"),
        el("ul", {}, (assessment.requiredChecks ?? []).map((check) => el("li", {}, checkNames[check] ?? formatValue(check)))),
        assessment.blockedReason ? el("p", { className: "hint hint--disabled", attrs: { role: "status" } }, assessment.blockedReason) : null,
    ]);
}

function renderMockPlan(plan, site) {
    return el("div", {}, [
        el("p", { className: "approval__note" }, "Simulated assessment and repair playback. These values are not measurements of a running site."),
        renderPlanSourceBadge(plan?.plan_source),
        el("p", {}, site?.org_name ?? "Demo site"),
        el("h3", {}, "Proposed changes"),
        el("p", {}, plan?.target_image ?? "Loading demo plan…"),
        el("details", { id: "approval-demo-config" }, [
            el("summary", { id: "approval-demo-config-summary" }, "Configuration details"),
            el("pre", {}, JSON.stringify(plan?.config ?? [], null, 2)),
        ]),
        el("p", {}, plan?.rationale ?? ""),
    ]);
}

export function renderApproval(root, snapshot, handlers) {
    const wasOpen = root.dataset.open === "true";
    clearElement(root);
    const { ui, sites, busy } = snapshot;
    if (!ui.approvalSiteId) {
        root.hidden = true;
        root.removeAttribute("data-open");
        return;
    }
    root.hidden = false;
    root.dataset.open = "true";
    const plan = ui.approvalPlan;
    const scope = ui.approvalSiteIds ?? [ui.approvalSiteId];
    const disabled = busy || ui.approvalLoading || ui.approvalSubmitting || !plan || plan.canRepair === false;
    const overlay = el("button", { className: "drawer-overlay", attrs: { type: "button", "aria-label": "Close assessment review", tabindex: "-1" } });
    overlay.addEventListener("click", handlers.closeApproval);
    const close = el("button", { className: "drawer__close", attrs: { id: "approval-close", type: "button", "aria-label": "Cancel approval", disabled: ui.approvalSubmitting ? "disabled" : undefined } }, "×");
    close.addEventListener("click", handlers.closeApproval);
    const approve = el("button", { className: "btn btn--primary", attrs: { id: "approval-approve-btn", type: "button", disabled: disabled ? "disabled" : undefined } }, ui.approvalSubmitting ? "Submitting approved scope…" : `Approve repair${scope.length > 1 ? ` for ${scope.length} sites` : ""}`);
    approve.addEventListener("click", () => handlers.onApprove(ui.approvalSiteId));
    const cancel = el("button", { className: "btn btn--secondary", attrs: { type: "button", id: "approval-cancel", disabled: ui.approvalSubmitting ? "disabled" : undefined } }, "Cancel");
    cancel.addEventListener("click", handlers.closeApproval);
    const body = el("div", { className: "drawer__body", id: `approval-body-${ui.approvalSiteId}` }, [
        el("p", { id: "approval-scope" }, `Repair scope: ${scope.map((id) => sites.find((site) => site.id === id)?.org_name ?? id).join(", ")}.`),
        scope.length > 1 ? el("p", { className: "approval__note" }, "The backend repairs this approved fleet sequentially, with fresh checks for each site.") : null,
    ]);
    if (ui.approvalLoading) {
        body.append(el("p", { attrs: { role: "status" } }, "Inspecting registered sites and checking the configured PHP policy…"));
    } else if (plan?.live) {
        if (plan.simulation) { body.append(el("p", { className: "approval__note" }, "Simulation — this backend does not modify or verify real sites.")); }
        for (const assessment of plan.assessments) { body.append(renderAssessment(assessment, sites)); }
        body.append(el("p", { className: "approval__note" }, `Approval is bound to these assessment fingerprints and policy ${plan.policyRevision}. Only registered local targets are included.`));
    } else if (plan) {
        body.append(renderMockPlan(plan, sites.find((site) => site.id === ui.approvalSiteId)));
    }
    if (ui.approvalError) {
        body.append(el("p", { className: "hint hint--disabled", attrs: { role: "alert" } }, ui.approvalError));
        if (!plan) {
            const retry = el("button", { className: "btn btn--secondary", attrs: { type: "button", disabled: ui.approvalSubmitting ? "disabled" : undefined } }, "Reassess this scope");
            retry.addEventListener("click", handlers.onRetry);
            body.append(retry);
        } else {
            body.append(el("p", { className: "hint" }, "Retrying approval keeps the same run submission key. Cancel and reassess if the backend reports a stale assessment."));
        }
    }
    const drawer = el("div", { className: "drawer", id: "approval-dialog", attrs: { role: "dialog", tabindex: "-1", "aria-modal": "true", "aria-labelledby": "approval-title", "aria-describedby": "approval-scope" } }, [
        el("header", { className: "drawer__header" }, [el("h2", { id: "approval-title", className: "drawer__title" }, "Review security assessment"), close]),
        body, el("footer", { className: "drawer__footer" }, [cancel, approve]),
    ]);
    root.append(overlay, drawer);
    if (!wasOpen) { requestAnimationFrame(() => document.getElementById("approval-cancel")?.focus()); }
}

export function bindApprovalEscape(handler) {
    const onKey = (event) => {
        const dialog = document.querySelector("#approval-root [role=dialog]");
        if (!dialog) { return; }
        if (event.key === "Escape") { event.preventDefault(); handler(); return; }
        if (event.key === "Tab") {
            const controls = [...dialog.querySelectorAll("button:not([disabled]), a[href], input:not([disabled]):not([type='hidden']), select:not([disabled]), textarea:not([disabled]), summary, [tabindex]")]
                .filter((control) => control.tabIndex >= 0 && !control.closest("[hidden], [inert]") && control.getClientRects().length > 0);
            if (!controls.length) { event.preventDefault(); dialog.focus(); return; }
            const first = controls[0];
            const last = controls[controls.length - 1];
            if (event.shiftKey && (document.activeElement === first || !dialog.contains(document.activeElement))) {
                event.preventDefault(); last.focus();
            } else if (!event.shiftKey && (document.activeElement === last || !dialog.contains(document.activeElement))) {
                event.preventDefault(); first.focus();
            }
        }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
}
