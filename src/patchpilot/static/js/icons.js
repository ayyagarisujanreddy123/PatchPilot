/** Small code-native icon set. Paths are constants; API data never enters SVG. */
const paths = {
    grid: ["M3 3h7v7H3z", "M14 3h7v7h-7z", "M3 14h7v7H3z", "M14 14h7v7h-7z"],
    activity: ["M3 12h4l3-8 4 16 3-8h4"],
    shield: ["M12 3 4 6v6c0 5 8 9 8 9s8-4 8-9V6z", "m8 12 3 3 5-6"],
    globe: ["M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0", "M3 12h18", "M12 3c5 5 5 13 0 18-5-5-5-13 0-18"],
    arrow: ["M5 12h14", "m13 6 6 6-6 6"],
    check: ["m5 12 4 4L19 6"],
    clock: ["M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0", "M12 7v5l3 2"],
    info: ["M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0", "M12 11v6", "M12 7h.01"],
    alert: ["m12 3 10 18H2z", "M12 9v5", "M12 17h.01"],
    refresh: ["M20 7v5h-5", "M4 17v-5h5", "M6 6a8 8 0 0 1 13 1l1 5", "M18 18a8 8 0 0 1-13-1l-1-5"],
    book: ["M4 4h6l2 2 2-2h6v16h-6l-2 2-2-2H4z", "M12 6v16"],
    external: ["M14 3h7v7", "m21 3-10 10", "M10 3H3v18h18v-7"],
    code: ["m8 6-6 6 6 6", "m16 6 6 6-6 6", "m14 3-4 18"],
};

export function icon(name, className = "") {
    const namespace = "http://www.w3.org/2000/svg";
    const svg = document.createElementNS(namespace, "svg");
    for (const [key, value] of Object.entries({ viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", "stroke-linecap": "round", "stroke-linejoin": "round", "aria-hidden": "true", focusable: "false", class: `icon ${className}` })) {
        svg.setAttribute(key, value);
    }
    for (const path of paths[name] ?? paths.info) {
        const element = document.createElementNS(namespace, "path");
        element.setAttribute("d", path);
        svg.append(element);
    }
    return svg;
}
