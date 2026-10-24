/**
 * Layout regions and global chrome (header, nav, banners).
 */

import { el, text, clearElement } from "../util.js";

export function renderHeader(root, { advisory, busy, mockMode }) {
    clearElement(root);
    const titleBlock = el("div", { className: "header__brand" }, [
        el("h1", { className: "header__title" }, "PatchPilot"),
        el("p", { className: "header__tagline" }, "Self-healing security for small businesses"),
    ]);

    const chipParts = [];
    if (advisory?.fixed_version) {
        chipParts.push(`PHP ${advisory.fixed_version}`);
    }
    if (advisory?.cves?.length) {
        chipParts.push(advisory.cves.join(" / "));
    }
    const advisoryChip = el(
        "div",
        {
            className: "chip chip--advisory",
            attrs: { role: "status", "aria-label": "Active advisory" },
        },
        chipParts.length ? chipParts.join(" · ") : "Advisory not loaded",
    );

    const busyIndicator = el(
        "div",
        {
            className: `busy-indicator${busy ? " busy-indicator--active" : ""}`,
            attrs: {
                role: "status",
                "aria-live": "polite",
                "aria-busy": busy ? "true" : "false",
            },
        },
        [
            el("span", { className: "busy-indicator__dot", attrs: { "aria-hidden": "true" } }),
            el("span", { className: "busy-indicator__label" }, busy ? "Busy" : "Ready"),
        ],
    );

    const mockBadge = mockMode
        ? el("span", { className: "chip chip--mock" }, "Demo data")
        : null;

    root.append(
        titleBlock,
        el("div", { className: "header__meta" }, [advisoryChip, mockBadge, busyIndicator].filter(Boolean)),
    );
}

export function renderNav(root, { route, onNavigate }) {
    clearElement(root);
    const items = [
        { id: "fleet", label: "Fleet" },
        { id: "metrics", label: "Metrics" },
        { id: "recipes", label: "Recipes" },
        { id: "events", label: "Event log" },
    ];
    const list = el(
        "ul",
        { className: "nav__list", attrs: { role: "tablist", "aria-label": "Main sections" } },
        items.map((item) => {
            const selected = route === item.id;
            const link = el(
                "a",
                {
                    className: "nav__link",
                    attrs: {
                        href: `#/${item.id}`,
                        role: "tab",
                        "aria-selected": selected ? "true" : "false",
                        id: `tab-${item.id}`,
                        "aria-controls": "app-main",
                    },
                },
                item.label,
            );
            link.addEventListener("click", (ev) => {
                ev.preventDefault();
                onNavigate(item.id);
            });
            return el("li", { className: "nav__item" }, link);
        }),
    );
    root.append(list);
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
