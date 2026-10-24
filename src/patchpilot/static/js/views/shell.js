/**
 * Layout regions and global chrome (header, nav, banners).
 */

import { el, text, clearElement } from "../util.js";
import { icon } from "../icons.js";

export function renderHeader(root, { advisory, busy, mockMode, health, route, websiteReport, websiteSubmitting, websiteLoading }) {
    clearElement(root);
    const website = route === "scan";
    const isBusy = website ? websiteSubmitting || ["QUEUED", "COLLECTING", "ANALYZING"].includes(websiteReport?.state) : busy;
    const simulation = mockMode || health?.mode === "SIMULATION";
    root.append(el("div", { className: "header__brand" }, [
        el("a", { className: "wordmark", attrs: { href: "/", "aria-label": "PatchPilot home" } }, [
            el("img", { attrs: { src: "/static/favicon.svg", alt: "", width: "30", height: "30" } }), "PatchPilot"]),
        el("span", { className: "header__divider", attrs: { "aria-hidden": "true" } }, "/"),
        el("span", { className: "header__workspace" }, "Security workspace"),
    ]), el("div", { className: "header__meta" }, [
        el("a", { className: "header__guide", attrs: { href: "/#workflow" } }, "Product guide", icon("book")),
        el("span", { className: `chip ${!website && simulation ? "chip--simulation" : ""}` }, website ? "Public website assessment" : simulation ? "Repair lab · simulated" : health?.mode === "REAL" ? "Repair lab · local fixtures" : "Connecting to repair lab"),
        el("span", { className: `busy-indicator ${isBusy ? "busy-indicator--active" : ""}` }, [
            el("span", { className: "busy-indicator__dot", attrs: { "aria-hidden": "true" } }),
            website ? websiteSubmitting ? "Starting…" : websiteLoading ? "Loading records" : websiteReport?.state === "COMPLETED" ? "Assessment completed" : websiteReport?.state === "FAILED" ? "Assessment stopped" : websiteReport ? "In progress" : "Ready" : busy ? "In progress" : health?.ready && health?.prepared ? "Ready" : "Setup needed"]),
    ]));
}

export function renderNav(root, { route, onNavigate, health }) {
    clearElement(root);
    const items = [
        { id: "scan", label: "Website assessment", symbol: "shield" },
        { id: "fleet", label: "Repair lab", symbol: "grid" },
        { id: "events", label: "Lab activity", symbol: "activity" },
    ];
    if (["MOCK", "SIMULATION"].includes(health?.mode)) {
        items.push({ id: "metrics", label: "Demo insights", symbol: "code" }, { id: "recipes", label: "Recipe memory", symbol: "book" });
    }
    const list = el(
        "ul",
        { className: "nav__list" },
        items.map((item) => {
            const selected = route === item.id;
            const link = el(
                "a",
                {
                    className: "nav__link",
                    attrs: {
                        href: `#/${item.id}`,
                        "aria-current": selected ? "page" : undefined,
                        id: `tab-${item.id}`,
                    },
                },
                [icon(item.symbol), item.label],
            );
            link.addEventListener("click", (ev) => {
                ev.preventDefault();
                onNavigate(item.id);
            });
            return el("li", { className: "nav__item" }, link);
        }),
    );
    root.append(el("span", { className: "nav__section-label" }, "Workspace"), list,
        el("div", { className: "nav__assurance" }, [icon("shield"), el("strong", {}, "Evidence before conclusions"),
            el("p", {}, "Fresh public responses. Clear coverage. Review every suggested fix.")]),
        el("a", { className: "nav__help", attrs: { href: "/#faq" } }, [icon("info"), "Help & product scope"]));
}

export function renderBackendBanner(root, { visible, message, onUseDemo }) {
    clearElement(root);
    if (!visible) {
        root.hidden = true;
        return;
    }
    root.hidden = false;
    root.append(
        el("p", { className: "banner__text" }, message || "Backend unreachable. Showing last known state."),
        el(
            "button",
            {
                className: "btn btn--secondary",
                attrs: { type: "button" },
            },
            "Use demo data",
        ),
    );
    const btn = root.querySelector("button");
    btn.addEventListener("click", onUseDemo);
}

export function renderPlaceholderPanel(root, { title, body, status }) {
    clearElement(root);
    root.append(
        el("h2", { className: "panel__title" }, title),
        el("p", { className: "panel__lede" }, body),
    );
    if (status) {
        root.append(el("p", { className: "panel__status", attrs: { role: "status" } }, status));
    }
}

export function renderShellStatusLine(root, snapshot) {
    clearElement(root);
    const { sites, mockMode, loading } = snapshot;
    if (loading) {
        root.append(text("Loading fleet state…"));
        return;
    }
    const count = sites?.length ?? 0;
    root.append(
        text(
            mockMode
                ? `Mock mode: ${count} registered site${count === 1 ? "" : "s"} at baseline.`
                : `${count} registered site${count === 1 ? "" : "s"} from API.`,
        ),
    );
}
