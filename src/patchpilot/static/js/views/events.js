/**
 * Append-only event log (read-only).
 */

import { clearElement, el } from "../util.js";

let lastScrolledEventCount = 0;
let wasOnEventsRoute = false;

function formatTimestamp(iso) {
    if (iso == null || iso === "") {
        return "—";
    }
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) {
        return String(iso);
    }
    return d.toLocaleString(undefined, {
        dateStyle: "short",
        timeStyle: "medium",
    });
}

function siteLabelForEvent(event, sites) {
    if (event.site_id == null || event.site_id === "") {
        return "System";
    }
    const site = sites?.find((s) => s.id === event.site_id);
    if (site?.org_name) {
        return `${site.org_name} (${event.site_id})`;
    }
    return String(event.site_id);
}

function filterEvents(events, siteFilter) {
    const list = events ?? [];
    if (!siteFilter || siteFilter === "all") {
        return list;
    }
    return list.filter((e) => e.site_id === siteFilter);
}

function renderEventRow(event, sites) {
    return el("li", { className: "event-log__row" }, [
        el("time", { className: "event-log__time", attrs: { datetime: event.ts ?? "" } }, formatTimestamp(event.ts)),
        el("span", { className: "event-log__site" }, siteLabelForEvent(event, sites)),
        el("span", { className: "event-log__stage" }, event.stage ?? "—"),
        el("span", { className: "event-log__message" }, event.message ?? "—"),
    ]);
}

export function renderEvents(root, snapshot, handlers) {
    clearElement(root);
    const { events, sites, ui } = snapshot;
    const filtered = filterEvents(events, ui.eventLogSiteFilter);

    root.append(el("h2", { className: "panel__title" }, "Event log"));
    root.append(
        el("p", { className: "panel__lede" }, "Append-only feed from the repair worker. Newest entries appear at the bottom."),
    );

    const filterId = "event-log-site-filter";
    const autoScrollId = "event-log-auto-scroll";

    const filterSelect = el(
        "select",
        {
            className: "event-log__select",
            id: filterId,
            attrs: { "aria-label": "Filter events by site" },
        },
        [
            el("option", { attrs: { value: "all" } }, "All sites"),
            ...(sites ?? []).map((site) =>
                el(
                    "option",
                    {
                        attrs: {
                            value: site.id,
                            selected: ui.eventLogSiteFilter === site.id ? "selected" : undefined,
                        },
                    },
                    `${site.org_name ?? site.id} (${site.id})`,
                ),
            ),
        ],
    );
    if (ui.eventLogSiteFilter && ui.eventLogSiteFilter !== "all") {
        filterSelect.value = ui.eventLogSiteFilter;
    } else {
        filterSelect.value = "all";
    }
    filterSelect.addEventListener("change", () => {
        handlers.onFilterSite(filterSelect.value === "all" ? "all" : filterSelect.value);
    });

    const autoScroll = el("input", {
        className: "event-log__checkbox",
        id: autoScrollId,
        attrs: {
            type: "checkbox",
            checked: ui.eventLogAutoScroll !== false ? "checked" : undefined,
        },
    });
    autoScroll.addEventListener("change", () => {
        handlers.onToggleAutoScroll(autoScroll.checked);
    });

    const toolbar = el("div", { className: "event-log__toolbar" }, [
        el("label", { className: "event-log__control", attrs: { for: filterId } }, [
            el("span", { className: "event-log__control-label" }, "Site"),
            filterSelect,
        ]),
        el("label", { className: "event-log__control event-log__control--checkbox", attrs: { for: autoScrollId } }, [
            autoScroll,
            el("span", {}, "Auto-scroll to newest"),
        ]),
    ]);
    root.append(toolbar);

    const scroll = el(
        "div",
        {
            className: "event-log__scroll",
            id: "event-log-scroll-region",
            attrs: {
                role: "log",
                "aria-live": "polite",
                "aria-relevant": "additions",
                tabindex: "0",
            },
        },
        [],
    );

    if (ui.loading && !(events?.length)) {
        scroll.append(el("p", { className: "run-muted", attrs: { role: "status" } }, "Loading events…"));
    } else if (!filtered.length) {
        scroll.append(el("p", { className: "empty-state" }, "No events yet."));
    } else {
        scroll.append(
            el(
                "ol",
                { className: "event-log__list" },
                filtered.map((event) => renderEventRow(event, sites)),
            ),
        );
    }

    root.append(scroll);
}

/**
 * Scroll feed to bottom when auto-scroll is on and new events arrived.
 */
export function afterRenderEvents(snapshot) {
    const { events, ui } = snapshot;
    if (ui.route !== "events") {
        wasOnEventsRoute = false;
        lastScrolledEventCount = 0;
        return;
    }
    if (!wasOnEventsRoute) {
        wasOnEventsRoute = true;
        lastScrolledEventCount = 0;
    }
    if (ui.eventLogAutoScroll === false) {
        return;
    }
    const count = events?.length ?? 0;
    if (count <= lastScrolledEventCount) {
        return;
    }
    lastScrolledEventCount = count;
    const region = document.getElementById("event-log-scroll-region");
    if (!region) {
        return;
    }
    const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    region.scrollTo({
        top: region.scrollHeight,
        behavior: reducedMotion ? "auto" : "smooth",
    });
}

export function resetEventsScrollTracking() {
    lastScrolledEventCount = 0;
}
