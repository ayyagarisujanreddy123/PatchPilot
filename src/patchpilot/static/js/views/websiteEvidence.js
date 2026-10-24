import { el } from "../util.js";
import { safeExternalUrl, websiteTimestamp } from "../website.js";

export function evidenceId(reportId, id) { return `website-evidence-${encodeURIComponent(reportId)}-${encodeURIComponent(id)}`; }

export function sourceLink(url, label = url) {
    const safe = safeExternalUrl(url);
    return safe ? el("a", { attrs: { href: safe, target: "_blank", rel: "noopener noreferrer" } }, label) : el("span", {}, label);
}

export function evidenceLinks(ids, report, context = "default") {
    return el("div", { className: "website-evidence-links" }, (ids ?? []).map((id) => {
        const recorded = report.evidence.find((item) => item.evidenceId === id);
        if (!recorded) { return el("span", { className: "muted" }, `${id} · evidence unavailable`); }
        const button = el("button", { className: "btn btn--small btn--secondary", attrs: { type: "button", id: `evidence-link-${encodeURIComponent(report.assessmentId)}-${encodeURIComponent(context)}-${encodeURIComponent(id)}` } }, `View evidence ${id}`);
        button.addEventListener("click", () => {
            const detail = document.getElementById(evidenceId(report.assessmentId, id));
            if (!detail) { return; }
            detail.open = true;
            let ancestor = detail.parentElement?.closest("details");
            while (ancestor) {
                ancestor.open = true;
                ancestor = ancestor.parentElement?.closest("details");
            }
            detail.querySelector("summary")?.focus({ preventScroll: true });
            detail.scrollIntoView({ block: "center", behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
        });
        return button;
    }));
}

function fact(label, value) { return el("div", {}, [el("dt", {}, label), el("dd", {}, value == null ? "Not recorded" : String(value))]); }

export function renderWebsiteEvidence(report) {
    const root = el("section", { className: "website-section", attrs: { "aria-labelledby": "website-evidence-heading" } }, [
        el("h3", { id: "website-evidence-heading" }, "Collected HTTP evidence"),
        el("p", { className: "muted" }, "Actual response metadata and observations collected for this assessment. Open a record for the details."),
    ]);
    if (!report.responses.length && !report.evidence.length) { root.append(el("p", {}, "No HTTP observations have been recorded yet.")); }
    report.responses.forEach((response, index) => root.append(el("details", { className: "website-evidence-card", id: `website-response-${report.assessmentId}-${index}` }, [
        el("summary", { id: `website-response-summary-${report.assessmentId}-${index}` }, [el("strong", {}, `HTTP ${response.status}`), el("span", {}, response.url)]),
        el("div", { className: "website-evidence-body" }, [
            sourceLink(response.url),
            el("dl", { className: "website-facts" }, [fact("Status", response.status), fact("Bytes read", response.bytesRead), fact("Elapsed", `${response.elapsedMs} ms`), fact("TLS", response.tlsProtocol), fact("Body truncated", response.truncated ? "Yes" : "No")]),
            el("h4", {}, "Response body SHA-256"), el("code", { className: "website-hash" }, response.bodySha256),
            el("h4", {}, "Recorded header names"), el("p", {}, response.headerNames.join(", ") || "None recorded"),
        ]),
    ])));
    report.evidence.forEach((item) => root.append(el("details", { className: "website-evidence-card", id: evidenceId(report.assessmentId, item.evidenceId) }, [
        el("summary", { id: `${evidenceId(report.assessmentId, item.evidenceId)}-summary` }, [el("strong", {}, item.evidenceId), el("span", {}, item.label)]),
        el("div", { className: "website-evidence-body" }, [
            el("p", { className: "website-observed" }, item.observed),
            el("dl", { className: "website-facts" }, [fact("Observation type", item.kind), fact("Collected", websiteTimestamp(item.collectedAt))]),
            sourceLink(item.url),
        ]),
    ])));
    return root;
}
