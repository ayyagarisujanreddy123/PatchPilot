/** Client/API contract checks only. No network or provider requests are made. */
import assert from "node:assert/strict";
import { validateWebsiteUrl, validateWebsiteReport, safeExternalUrl, WEBSITE_ACTIVE_STATES } from "../js/website.js";
assert.equal(validateWebsiteUrl(" http://php.testsparker.com/ "), "http://php.testsparker.com/");
assert.equal(validateWebsiteUrl("https://www.php.net/#documentation"), "https://www.php.net/");
for (const url of ["http://127.0.0.1/", "http://localhost/", "http://10.0.0.2/", "http://172.16.0.1/", "http://192.168.1.1/", "http://169.254.169.254/", "http://100.64.0.1/", "http://2130706433/", "http://[::1]/", "http://[fc00::1]/", "http://[2001:db8::1]/", "http://192.0.2.1/", "http://198.51.100.1/", "http://203.0.113.1/", "http://user:secret@www.php.net/", "ftp://www.php.net/", "javascript:alert(1)", "https://www.php.net:8080/", "https://www.php.net/?token=private"]) {
    assert.throws(() => validateWebsiteUrl(url), undefined, `must reject ${url}`);
}
assert.equal(safeExternalUrl("javascript:alert(1)"), null);
assert.equal(safeExternalUrl("https://www.php.net/"), "https://www.php.net/");
assert.ok(WEBSITE_ACTIVE_STATES.has("COLLECTING"));
assert.ok(!WEBSITE_ACTIVE_STATES.has("COMPLETED"));
assert.throws(() => validateWebsiteReport({state:"COMPLETED"}), /incomplete website report/);
globalThis.window = { location: { search: "?mock=1" } };
let sessionCalls = 0;
const calls = [];
const failed = { assessmentId: "scan-real", url: "http://php.testsparker.com/", state: "FAILED", createdAt: "2026-10-24T12:00:00Z", finishedAt: "2026-10-24T12:00:03Z", stageMessage: "Provider analysis failed", responses: [{ url: "http://php.testsparker.com/", status: 200, elapsedMs: 42, bodySha256: "a".repeat(64), bytesRead: 800, truncated: false, tlsProtocol: null, headerNames: ["content-type"] }], evidence: [], phpDetection: {status:"UNKNOWN",version:null,explanation:"No PHP banner was observed",evidenceIds:[]}, findings: [], analysis: null, coverage: ["Public response"], limitations: ["Installed package status requires server access"], events: [], error: "Provider unavailable" };
globalThis.fetch = async (path, init) => {
    calls.push({ path, ...init });
    assert.ok(path.startsWith("/api/"));
    assert.equal(init.credentials, "same-origin");
    let body;
    if (path === "/api/session") { sessionCalls += 1; body = { csrfToken: "scan-csrf" }; }
    else if (path === "/api/website-assessments/examples") { body = { items: [{ id: "sample", title: "Public sample", url: "http://php.testsparker.com/" }] }; }
    else if (path === "/api/website-assessments" && init.method === "POST") {
        assert.equal(init.headers["X-CSRF-Token"], "scan-csrf");
        assert.deepEqual(JSON.parse(init.body), { url: "http://php.testsparker.com/" });
        body = { assessmentId: "scan-real", statusUrl: "/api/website-assessments/scan-real" };
    } else if (path === "/api/website-assessments") { body = { items: [failed], nextCursor: null }; }
    else if (path === "/api/website-assessments/scan-real") { body = failed; }
    else { throw new Error(`Unexpected lab or external request: ${path}`); }
    return { status: 200, ok: true, json: async () => body };
};
const api = await import("../js/api.js");
const [examples, history] = await Promise.all([api.getWebsiteExamples(), api.getWebsiteAssessmentHistory()]);
assert.equal(sessionCalls, 1, "parallel initial reads share the same session establishment");
assert.equal(examples[0].url, "http://php.testsparker.com/");
assert.equal(calls.filter(call=>call.method === "POST").length, 0, "loading sample metadata must not start an assessment");
assert.equal((await api.createWebsiteAssessment(examples[0].url)).assessmentId, "scan-real", "lab mock query must not substitute a canned website report");
const report = await api.getWebsiteAssessment("scan-real");
assert.equal(report.state, "FAILED");
assert.equal(report.analysis, null);
assert.equal(report.responses[0].bodySha256, "a".repeat(64));
assert.equal(report.phpDetection.status, "UNKNOWN");
assert.equal(history[0].error, "Provider unavailable");
console.log("PASS: public URL validation, private/reserved/query rejection, safe reference URLs, real website API under lab mock query, CSRF/session coalescing, fill-only examples, partial failure evidence and unknown PHP preservation.");
