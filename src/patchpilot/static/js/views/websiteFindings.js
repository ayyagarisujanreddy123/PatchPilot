import { el } from "../util.js";
import { evidenceLinks, sourceLink } from "./websiteEvidence.js";

export function renderWebsiteFindings(report) {
    const root = el("section", { className: "website-section", attrs: { "aria-labelledby": "website-findings-heading" } }, [
        el("h3", { id: "website-findings-heading" }, "Findings from public responses"),
        el("p", { className: "muted" }, "Severity describes the reported observation; confidence and linked evidence explain what was actually seen."),
    ]);
    if (!report.findings.length) {
        root.append(el("p", {}, report.state === "COMPLETED" ? "No configuration findings were reported from the collected responses. Review the coverage and further checks below." : "No findings have been recorded yet."));
    }
    report.findings.forEach((finding) => root.append(el("article", { className: "website-finding", id: `website-finding-${report.assessmentId}-${finding.findingId}` }, [
        el("div", { className: "website-finding-heading" }, [el("h4", {}, finding.title), el("span", { className: `website-severity website-severity--${finding.severity}` }, finding.severity), el("span", { className: "chip" }, finding.confidence === "OBSERVED" ? "Observed" : "Inferred")]),
        el("p", {}, finding.description), el("p", {}, [el("strong", {}, "Recommendation: "), finding.recommendation]),
        evidenceLinks(finding.evidenceIds, report, `finding-${finding.findingId}`),
        finding.references.length ? el("ul", { className: "website-references" }, finding.references.map((url, index) => el("li", {}, sourceLink(url, `Reference ${index + 1} · ${url}`)))) : null,
    ])));
    return root;
}

function copyCodeButton(code, id) {
    const feedback = el("span", { className: "muted", attrs: { role: "status" } });
    const button = el("button", { className: "btn btn--small btn--secondary", attrs: { type: "button", id } }, "Copy suggested code");
    button.addEventListener("click", async () => {
        try {
            if (!navigator.clipboard?.writeText) { throw new Error("Clipboard unavailable"); }
            await navigator.clipboard.writeText(code);
            feedback.textContent = "Code copied. Review it before applying.";
        } catch { feedback.textContent = "Clipboard unavailable. Select and copy the code below."; }
    });
    return el("div", { className: "website-copy-row" }, [button, feedback]);
}

export function renderWebsiteAnalysis(report) {
    const analysis = report.analysis;
    const root = el("section", { className: "website-section", attrs: { "aria-labelledby": "website-analysis-heading" } }, [el("h3", { id: "website-analysis-heading" }, "Anthropic remediation guidance")]);
    if (!analysis) {
        root.append(el("p", {}, report.state === "FAILED" ? "No Anthropic analysis was recorded. The collected evidence above remains available." : "Anthropic analysis has not been recorded yet."));
        return root;
    }
    root.append(el("p", {}, analysis.summary), el("p", { className: "website-scope-note" }, "Suggested changes require review and access to the website's configuration or source. This assessment does not apply a patch."));
    root.append(el("details", { id: `website-provider-${report.assessmentId}`, className: "website-provider" }, [
        el("summary", { id: `website-provider-summary-${report.assessmentId}` }, `Analysis provenance · ${analysis.source} · ${analysis.modelId}`),
        el("dl", { className: "website-facts" }, [
            el("div", {}, [el("dt", {}, "Provider message"), el("dd", {}, analysis.providerMessageId)]),
            el("div", {}, [el("dt", {}, "Input / output tokens"), el("dd", {}, `${analysis.inputTokens} / ${analysis.outputTokens}`)]),
        ]),
    ]));
    analysis.recommendations.forEach((recommendation, index) => {
        const finding = report.findings.find((item) => item.findingId === recommendation.findingId);
        root.append(el("article", { className: "website-remediation" }, [
            el("h4", {}, finding?.title ?? recommendation.findingId), el("p", {}, recommendation.explanation),
            recommendation.requiresServerAccess ? el("p", { className: "chip" }, "Requires authorized server access") : null,
            el("ol", {}, recommendation.steps.map((step) => el("li", {}, step))),
            recommendation.code ? el("div", {}, [copyCodeButton(recommendation.code, `website-copy-${report.assessmentId}-${index}`), el("pre", { className: "website-code" }, el("code", {}, recommendation.code))]) : null,
            el("p", {}, [el("strong", {}, "Verify the change: "), recommendation.verification]),
            finding ? evidenceLinks(finding.evidenceIds, report, `analysis-${index}`) : null,
        ]));
    });
    if (analysis.furtherChecks.length) { root.append(el("h4", {}, "Further checks requiring more access"), el("ul", {}, analysis.furtherChecks.map((check) => el("li", {}, check)))); }
    return root;
}
