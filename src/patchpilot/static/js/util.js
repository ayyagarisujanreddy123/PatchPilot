/**
 * Build DOM with text nodes only for dynamic strings (no innerHTML for API data).
 */

export function clearElement(el) {
    while (el.firstChild) {
        el.removeChild(el.firstChild);
    }
}

export function text(str) {
    return document.createTextNode(str == null || str === "" ? "—" : String(str));
}

export function el(tag, options = {}, ...children) {
    const node = document.createElement(tag);
    const { className, id, attrs = {}, dataset = {} } = options;

    if (className) {
        node.className = className;
    }
    if (id) {
        node.id = id;
    }
    for (const [key, value] of Object.entries(attrs)) {
        if (value != null) {
            node.setAttribute(key, String(value));
        }
    }
    for (const [key, value] of Object.entries(dataset)) {
        node.dataset[key] = String(value);
    }
    for (const child of children.flat()) {
        if (child == null) {
            continue;
        }
        if (typeof child === "string" || typeof child === "number") {
            node.appendChild(text(child));
        } else {
            node.appendChild(child);
        }
    }
    return node;
}

export function appendChildren(parent, ...children) {
    for (const child of children.flat()) {
        if (child == null) {
            continue;
        }
        if (typeof child === "string" || typeof child === "number") {
            parent.appendChild(text(child));
        } else {
            parent.appendChild(child);
        }
    }
    return parent;
}

export function formatDuration(ms) {
    if (ms == null || Number.isNaN(Number(ms))) {
        return "—";
    }
    const n = Number(ms);
    if (n < 1000) {
        return `${n} ms`;
    }
    return `${(n / 1000).toFixed(n >= 10000 ? 0 : 1)} s`;
}

export function readSearchParams() {
    return new URLSearchParams(window.location.search);
}

export function scenarioFromUrl() {
    const s = readSearchParams().get("scenario");
    if (s === "rollback" || s === "restorefail") {
        return s;
    }
    return "default";
}

export function isMockRequestedInUrl() {
    return readSearchParams().get("mock") === "1";
}
