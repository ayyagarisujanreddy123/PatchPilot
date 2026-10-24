/** Compact records maintain their information order on small screens. */
import { el } from "../util.js";
import { icon } from "../icons.js";
import { isRepairEligible, renderStatusBadge, planSourceLabel, formatChecks } from "./badges.js";

function siteRow(site, handlers, disabled) {
    const review = el("button", { className: "btn btn--secondary btn--small", attrs: {
        id: `assess-site-${site.id}`, type: "button", disabled: !disabled && isRepairEligible(site.status) ? undefined : "disabled",
        "aria-label": `Assess ${site.org_name}`,
    } }, "Assess", icon("arrow"));
    review.addEventListener("click", () => handlers.openApproval(site.id));
    const report = el("a", { className: "site-report", attrs: { id: `view-run-${site.id}`, href: `#/run/${site.id}`,
        "aria-label": `View report for ${site.org_name}` } }, site.last_run_id ? "View report" : "Run details");
    report.addEventListener("click", (event) => { event.preventDefault(); handlers.viewRun(site.id); });
    const useUrl = el("button", { className: "site-url", attrs: { type: "button", id: `use-url-${site.id}`,
        "aria-label": `Use ${site.address} in the assessment form` } }, site.address);
    useUrl.addEventListener("click", () => handlers.onSelectSite(site.address));
    return el("li", { className: "site-row" }, [
        el("div", { className: "site-row__identity" }, [el("span", { className: `site-avatar ${site.type === "upload" ? "site-avatar--upload" : ""}` }, icon("globe")),
            el("div", {}, [el("h3", {}, site.org_name), useUrl,
                el("span", { className: "site-capability" }, site.type === "upload" ? "Homepage · contact · uploads" : "Homepage · contact")])]),
        el("div", { className: "site-row__runtime" }, [el("span", { className: "mobile-label" }, "Runtime"),
            el("strong", {}, site.php_version ? `PHP ${site.php_version}` : "Not assessed"),
            el("span", { className: "site-detail" }, site.checks_required != null && site.checks_passed != null ? `${formatChecks(site.checks_passed, site.checks_required)} checks` : "Verification pending")]),
        el("div", { className: "site-row__status" }, [renderStatusBadge(site.status), site.plan_source ? el("span", { className: "site-detail" }, planSourceLabel(site.plan_source)) : null]),
        el("div", { className: "site-row__actions" }, [review, report]),
    ]);
}

export function renderSites(sites, handlers, disabled) {
    if (!sites.length) return el("div", { className: "empty-state" }, [icon("globe"), el("h3", {}, "No sites in this view"), el("p", {}, "Choose All sites to return to your registered workspace.")]);
    return el("div", { className: "site-register" }, [
        el("div", { className: "site-register__head", attrs: { "aria-hidden": "true" } }, ["Website", "Runtime", "Status", "Actions"].map((label) => el("span", {}, label))),
        el("ul", { className: "site-register__list", attrs: { "aria-label": "Registered PHP sites" } }, sites.map((site) => siteRow(site, handlers, disabled))),
    ]);
}
