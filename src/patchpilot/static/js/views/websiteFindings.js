import { el } from "../util.js";
import { icon } from "../icons.js";
import { evidenceLinks, sourceLink } from "./websiteEvidence.js";

function severity(finding) {
    return el("span", { className: `website-severity website-severity--${finding.severity}` }, `${finding.severity} priority`);
}

export function renderWebsiteFindings(report) {
    const root = el("section", { className: "website-section", attrs: { "aria-labelledby": "website-findings-heading" } }, [
        el("h3", { id: "website-findings-heading" }, "Findings from public responses"),
        el("p", { className: "muted" }, "These observations describe the public response. They do not confirm an exploitable vulnerability."),
    ]);
    report.findings.forEach((finding) => root.append(el("details", { className: "website-finding", id: `website-finding-${report.assessmentId}-${finding.findingId}` }, [
        el("summary", { id: `website-finding-summary-${report.assessmentId}-${finding.findingId}` }, [el("span", { className: "website-action__title" }, finding.title), severity(finding)]),
        el("div", { className: "website-action__body" }, [el("p", {}, finding.description),
            el("p", { className: "chip" }, finding.confidence === "OBSERVED" ? "Observed in response" : "Inferred — needs confirmation"),
            el("p", {}, [el("strong", {}, "Next step: "), finding.recommendation]), evidenceLinks(finding.evidenceIds, report, `finding-${finding.findingId}`),
            finding.references.length ? el("ul", { className: "website-references" }, finding.references.map((url, index) => el("li", {}, sourceLink(url, `Reference ${index + 1}`)))) : null,
        ]),
    ])));
    return root;
}

function copyCodeButton(code, id) {
    const feedback = el("span", { className: "muted", attrs: { role: "status" } });
    const button = el("button", { className: "btn btn--small btn--secondary", attrs: { type: "button", id } }, "Copy code");
    button.addEventListener("click", async () => {
        try {
            if (!navigator.clipboard?.writeText) { throw new Error("Clipboard unavailable"); }
            await navigator.clipboard.writeText(code);
            feedback.textContent = "Copied. Review before applying.";
        } catch { feedback.textContent = "Select and copy the code below."; }
    });
    return el("div", { className: "website-copy-row" }, [button, feedback]);
}

const actionTitles = {
    "php-unsupported-branch": "Check and upgrade the PHP runtime",
    "unencrypted-http": "Enable HTTPS for your website",
    "php-version-disclosure": "Hide PHP version details",
    "content-security-policy": "Add a Content Security Policy",
    "x-content-type-options": "Prevent content-type guessing",
    "framing-policy": "Control where your site can be embedded",
    "hsts-policy": "Keep visitors on HTTPS",
    "php-session-cookie": "Strengthen PHP session cookies",
    "php-error-disclosure": "Keep PHP error details private",
    "php-diagnostic-page": "Restrict the PHP diagnostic page",
};

export function renderWebsiteProvenance(report) {
    const analysis = report.analysis;
    if (!analysis) { return null; }
    return el("details", { id: `website-provider-${report.assessmentId}`, className: "website-provider" }, [
        el("summary", { id: `website-provider-summary-${report.assessmentId}` }, "Analysis provenance"),
        el("dl", { className: "website-facts" }, [
            el("div", {}, [el("dt", {}, "Provider / model"), el("dd", {}, `${analysis.source} / ${analysis.modelId}`)]),
            el("div", {}, [el("dt", {}, "Provider message"), el("dd", {}, analysis.providerMessageId)]),
            el("div", {}, [el("dt", {}, "Input / output tokens"), el("dd", {}, `${analysis.inputTokens} / ${analysis.outputTokens}`)]),
        ]),
    ]);
}

export function renderWebsiteAnalysis(report) {
    const analysis = report.analysis;
    if (!analysis) {
        return report.state === "FAILED" ? el("p", { className: "website-scope-note" }, "AI recommendations aren't available for this assessment. Review any collected findings or try again.") : null;
    }
    const root = el("section", { className: "website-section website-recommendations", attrs: { "aria-labelledby": "website-analysis-heading" } }, [
        el("div", { className: "section-heading" }, [el("h2", { id: "website-analysis-heading" }, "What to fix first"), el("span", { className: "website-ai-label" }, [icon("code"), "Analyzed by Victor · Powered by Anthropic"])]),
    ]);
    if (analysis.summary.length > 240) {
        const first = analysis.summary.match(/^.{1,220}?(?:[.!?](?:\s|$)|$)/)?.[0]?.trim();
        if (first) { root.append(el("p", { className: "website-summary" }, first)); }
        root.append(el("details", { className: "website-summary-details", id: `website-ai-summary-${report.assessmentId}` }, [el("summary", { id: `website-ai-summary-toggle-${report.assessmentId}` }, "Read the AI summary"), el("p", {}, analysis.summary)]));
    } else { root.append(el("p", { className: "website-summary" }, analysis.summary)); }
    const list = el("div", { className: "website-action-list" });
    analysis.recommendations.forEach((recommendation, index) => {
        const finding = report.findings.find((item) => item.findingId === recommendation.findingId);
        if (!finding) { return; }
        list.append(el("details", { className: "website-action", id: `website-action-${report.assessmentId}-${recommendation.findingId}` }, [
            el("summary", { id: `website-action-summary-${report.assessmentId}-${recommendation.findingId}` }, [
                el("span", { className: "website-action__number", attrs: { "aria-hidden": "true" } }, String(index + 1).padStart(2, "0")),
                el("span", { className: "website-action__title" }, actionTitles[finding.findingId] ?? finding.title), severity(finding),
                el("span", { className: "website-action__chevron" }, ["Review fix", icon("arrow")]),
            ]),
            el("div", { className: "website-action__body" }, [el("p", {}, recommendation.explanation),
                el("ol", {}, recommendation.steps.map((step) => el("li", {}, step))),
                recommendation.code ? el("details", { className: "website-code-details", id: `website-code-details-${report.assessmentId}-${index}` }, [
                    el("summary", { id: `website-code-summary-${report.assessmentId}-${index}` }, [icon("code"), "View suggested code"]),
                    el("div", {}, [copyCodeButton(recommendation.code, `website-copy-${report.assessmentId}-${index}`), el("pre", { className: "website-code" }, el("code", {}, recommendation.code))]),
                ]) : null,
                el("p", {}, [el("strong", {}, "Verify the change: "), recommendation.verification]), evidenceLinks(finding.evidenceIds, report, `analysis-${index}`),
            ]),
        ]));
    });
    root.append(list);
    if (!analysis.recommendations.length) { root.append(el("p", {}, "No fixes were suggested from these public observations. Review coverage before drawing conclusions.")); }
    if (analysis.furtherChecks.length) { root.append(el("details", { className: "website-further-checks", id: `website-further-${report.assessmentId}` }, [
        el("summary", { id: `website-further-summary-${report.assessmentId}` }, "Checks that need server access"), el("ul", {}, analysis.furtherChecks.map((check) => el("li", {}, check))),
    ])); }
    return root;
}
