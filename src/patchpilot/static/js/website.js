/** Client shape checks only. The server validates DNS, redirects, and destinations. */
export const WEBSITE_ACTIVE_STATES = new Set(["QUEUED", "COLLECTING", "ANALYZING"]);

export function validateWebsiteReport(report) {
    const states = [...WEBSITE_ACTIVE_STATES, "COMPLETED", "FAILED"];
    if (!report || typeof report.assessmentId !== "string" || typeof report.url !== "string" || !states.includes(report.state)
        || !["responses", "evidence", "findings", "coverage", "limitations", "events"].every((key) => Array.isArray(report[key]))
        || !["REPORTED", "INFERRED", "UNKNOWN"].includes(report.phpDetection?.status) || !Array.isArray(report.phpDetection?.evidenceIds)
        || (report.analysis && (report.analysis.source !== "ANTHROPIC" || !Array.isArray(report.analysis.recommendations) || !Array.isArray(report.analysis.furtherChecks)))) {
        throw new Error("The backend returned an incomplete website report. Last recorded observations remain visible; no replacement result was generated.");
    }
    return report;
}

export function validateWebsiteUrl(input) {
    let url;
    try { url = new URL(input.trim()); } catch { throw new Error("Enter a complete public URL beginning with https:// or http://."); }
    if (!["http:", "https:"].includes(url.protocol)) { throw new Error("Use a public HTTP or HTTPS website URL."); }
    if (url.username || url.password) { throw new Error("Enter a URL without credentials."); }
    if (url.search) { throw new Error("Remove query parameters before assessing this public page."); }
    if (url.port && !["80", "443"].includes(url.port)) { throw new Error("Website assessments support public web ports 80 and 443."); }
    const host = url.hostname.toLowerCase();
    const privateName = host === "localhost" || !host.includes(".") || /\.(localhost|local|internal|home|test|invalid|example)$/.test(host);
    let privateAddress = false;
    if (/^\d+\.\d+\.\d+\.\d+$/.test(host)) {
        const [a, b, c] = host.split(".").map(Number);
        privateAddress = a === 0 || a === 10 || a === 127 || a >= 224 || (a === 169 && b === 254)
            || (a === 172 && b >= 16 && b <= 31) || (a === 192 && (b === 168 || b === 0 && (c === 0 || c === 2)))
            || (a === 100 && b >= 64 && b <= 127) || (a === 198 && (b === 18 || b === 19 || b === 51 && c === 100))
            || (a === 203 && b === 0 && c === 113);
    }
    if (host.startsWith("[")) {
        const first = Number.parseInt(host.slice(1).split(":")[0], 16);
        privateAddress = !(first >= 0x2000 && first <= 0x3fff) || host.startsWith("[2001:db8:");
    }
    if ((privateName && !host.startsWith("[")) || privateAddress) {
        throw new Error("Enter a public internet website. Local, private, and reserved destinations are excluded from website assessments; local fixtures belong in Repair lab.");
    }
    url.hash = "";
    return url.href;
}

export function safeExternalUrl(value) {
    try { const url = new URL(value); return ["http:", "https:"].includes(url.protocol) && !url.username && !url.password ? url.href : null; }
    catch { return null; }
}

export function websiteTimestamp(value) {
    if (!value) { return "Not recorded"; }
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "medium" });
}
