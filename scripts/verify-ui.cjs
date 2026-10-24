#!/usr/bin/env node
/**
 * Browser QA without real repair/reset/model calls.
 *
 * PATCHPILOT_URL=http://127.0.0.1:8765
 * PLAYWRIGHT_MODULE=/absolute/path/to/node_modules/playwright (optional)
 * CHROME_EXECUTABLE=/path/to/chrome (optional; installed macOS Chrome is detected)
 * PATCHPILOT_SCREENSHOTS=var/ui-qa (optional)
 * AXE_MODULE=/absolute/path/to/node_modules/axe-core (optional)
 *
 * The only dependency is Playwright, installed outside this repository if needed.
 * Repair mutations use ?mock=1. Website states use intercepted API responses;
 * their synthetic POST is fulfilled in this browser and never reaches the API.
 * The network guard blocks every other HTTP write and every external request.
 */

"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const playwrightModule = process.env.PLAYWRIGHT_MODULE || "playwright";
let chromium;
try {
    ({ chromium } = require(playwrightModule));
} catch {
    console.error("Install Playwright outside the repository and set PLAYWRIGHT_MODULE to its package path.");
    process.exit(2);
}

const base = new URL(process.env.PATCHPILOT_URL || "http://127.0.0.1:8765");
assert(["http:", "https:"].includes(base.protocol), "PATCHPILOT_URL must be an HTTP(S) URL");
assert(["127.0.0.1", "localhost", "[::1]"].includes(base.hostname), "UI QA accepts a loopback controller only");
const origin = base.origin;
const screenshots = process.env.PATCHPILOT_SCREENSHOTS
    ? path.resolve(process.env.PATCHPILOT_SCREENSHOTS) : null;
if (screenshots) fs.mkdirSync(screenshots, { recursive: true });

const results = [];
const pageErrors = [];
const consoleErrors = [];
const externalRequests = [];
const blockedWrites = [];
const interceptedWrites = [];
const performanceSamples = [];
const widths = [320, 768, 1024, 1440];
const pollWindowMs = 4500;
let browser;

function optionalAxe() {
    const candidates = [process.env.AXE_MODULE, "axe-core"].filter(Boolean);
    try {
        candidates.push(require.resolve("axe-core", { paths: [path.dirname(require.resolve(playwrightModule))] }));
    } catch {}
    for (const candidate of candidates) {
        try { return require(candidate).source; } catch {}
    }
    return null;
}
const axeSource = optionalAxe();

function slug(value) { return value.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, ""); }

async function screenshot(page, label) {
    if (screenshots && !page.isClosed()) {
        await page.screenshot({ path: path.join(screenshots, `${slug(label)}.png`), fullPage: true });
    }
}

async function check(name, operation, page = null) {
    try {
        await operation();
        results.push({ name, passed: true });
        console.log(`PASS ${name}`);
        return true;
    } catch (error) {
        const message = error?.message || String(error);
        results.push({ name, passed: false, message });
        console.error(`FAIL ${name}: ${message}`);
        if (page) await screenshot(page, `failed-${name}`).catch(() => {});
        return false;
    }
}

async function newPage(options = {}) {
    const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, reducedMotion: options.reducedMotion || "reduce" });
    await context.addInitScript(() => {
        window.__patchpilotQaPerf = { mainReplacements: 0, mutationRecords: 0, longTasks: [] };
        new MutationObserver(records => {
            const performance = window.__patchpilotQaPerf;
            for (const record of records) {
                if (record.target.id === "app-main" && record.removedNodes.length) performance.mainReplacements += 1;
                if (record.target.id === "app-main" || record.target.closest?.("#app-main")) performance.mutationRecords += 1;
            }
        }).observe(document, { childList: true, subtree: true });
        if (PerformanceObserver.supportedEntryTypes.includes("longtask")) {
            new PerformanceObserver(list => {
                window.__patchpilotQaPerf.longTasks.push(...list.getEntries().map(entry => Math.round(entry.duration)));
            }).observe({ type: "longtask", buffered: true });
        }
    });
    const requests = [];
    context.on("request", request => requests.push({ url: request.url(), method: request.method() }));
    await context.route("**/*", async route => {
        const request = route.request();
        const target = new URL(request.url());
        if (!["http:", "https:"].includes(target.protocol)) return route.continue();
        if (target.origin !== origin) {
            externalRequests.push({ url: target.href, method: request.method() });
            return route.abort("blockedbyclient");
        }
        const intercepted = await options.intercept?.(request, target);
        if (intercepted) {
            if (!["GET", "HEAD", "OPTIONS"].includes(request.method())) {
                interceptedWrites.push({ path: target.pathname, method: request.method() });
            }
            return route.fulfill({ status: intercepted.status ?? 200, contentType: "application/json",
                body: JSON.stringify(intercepted.json) });
        }
        // Completed synthetic assessments may reveal the optional owner next step.
        // Keep its initial reads local to this harness, including selection-race tests.
        if (request.method() === "GET" && ["/api/repository-connections/status", "/api/repository-connections", "/api/repository-repairs"].includes(target.pathname)) {
            const json = target.pathname.endsWith("/status")
                ? { available: false, login: null, message: "GitHub is not connected in this browser test." }
                : { items: [], nextCursor: null };
            return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(json) });
        }
        if (!["GET", "HEAD", "OPTIONS"].includes(request.method())) {
            blockedWrites.push({ path: target.pathname, method: request.method() });
            return route.abort("blockedbyclient");
        }
        return route.continue();
    });
    const page = await context.newPage();
    page.setDefaultTimeout(10000);
    page.on("pageerror", error => pageErrors.push(error.message));
    page.on("console", message => {
        if (message.type() === "error") consoleErrors.push(message.text());
    });
    return { context, page, requests };
}

function websiteReport(state = "COMPLETED") {
    const timestamp = "2026-10-24T12:00:00Z";
    const url = "https://example.org/public/index.php";
    const titles = ["PHP version banner is publicly visible", "HTTP transport needs review", "Content policy is absent",
        "Framing policy is absent", "Content type protection is absent", "Response text is safely escaped"];
    const evidence = titles.map((title, index) => ({ evidenceId: `e${index + 1}`, url, kind: "HTTP_HEADER",
        label: title, observed: index === 5 ? '<img src=x onerror="globalThis.__patchpilotXss=1"> & <script>globalThis.__patchpilotXss=1</script>'
            : `${title}: actual browser QA response fixture; no target was contacted. ${"bounded evidence ".repeat(8)}`,
        collectedAt: timestamp }));
    const findings = titles.map((title, index) => ({ findingId: `finding-${index + 1}`, title,
        severity: index < 2 ? "high" : index < 4 ? "medium" : "low", confidence: "OBSERVED",
        description: `Browser-intercepted QA observation ${index + 1}; this is not a real website assessment.`,
        evidenceIds: [`e${index + 1}`], recommendation: "Review the recorded response and apply an authorized configuration change.",
        references: index === 5 ? ["javascript:globalThis.__patchpilotXss=1", "https://www.php.net/"] : ["https://www.php.net/"] }));
    const active = ["QUEUED", "COLLECTING", "ANALYZING"].includes(state);
    return { assessmentId: "qa-website-completed", url, state, createdAt: timestamp,
        finishedAt: active ? null : "2026-10-24T12:00:10Z",
        stageMessage: active ? "Browser QA: analyzing intercepted evidence; no model or website request was sent."
            : state === "FAILED" ? "Browser QA: provider unavailable; partial HTTP evidence retained."
                : "Browser QA: recorded evidence and synthetic guidance are ready for review.",
        responses: [{ url, status: 200, elapsedMs: 121, bodySha256: "a".repeat(64), bytesRead: 136,
            truncated: false, tlsProtocol: "TLSv1.3", headerNames: ["content-type", "x-powered-by"] }],
        evidence: active ? evidence.slice(0, 1) : evidence,
        phpDetection: { status: "REPORTED", version: "5.2.6", explanation: "The intercepted response fixture reports PHP/5.2.6; installed patch status is unknown.", evidenceIds: ["e1"] },
        findings: active ? [] : findings,
        analysis: state === "COMPLETED" ? { source: "ANTHROPIC", modelId: "qa-intercepted-model",
            providerMessageId: "qa-no-provider-call", inputTokens: 2787, outputTokens: 1253,
            summary: "Synthetic browser QA guidance: review the evidence before any server-side change.",
            recommendations: findings.slice(0, 3).map((finding, index) => ({ findingId: finding.findingId,
                explanation: `Review ${finding.title.toLowerCase()} with authorized server access.`,
                steps: ["Record the original configuration.", "Apply the reviewed change in a separate environment.", "Repeat the original HTTP observation."],
                code: index === 2 ? '<script>globalThis.__patchpilotXss=1</script>\n' + "x".repeat(240)
                    : `# QA example only\nHeader always set X-QA-Review \"required\"\n${"# long unbroken line ".repeat(12)}`,
                verification: "Compare fresh response evidence after an authorized change; do not infer a verified repair from this report.",
                requiresServerAccess: true })), furtherChecks: ["Inspect installed package and backport status with authorized server access."] } : null,
        coverage: ["One bounded public GET and its redirect chain; browser QA interception only."],
        limitations: ["No authenticated pages, source code, server package metadata, active payloads, or exploit testing.",
            "An assessment is not a verified repair or a declaration that a website is safe."],
        events: Array.from({ length: 10 }, (_, index) => ({ sequence: index + 1, timestamp,
            stage: index < 2 ? "COLLECTING" : active ? state : index === 9 ? state : "ANALYZING",
            message: `Browser QA recorded activity ${index + 1}; no network probe or provider call.` })),
        error: state === "FAILED" ? "The analysis provider was unavailable. Collected HTTP evidence remains available." : null };
}

function websiteInterception() {
    const fixture = { report: null, posts: [], reads: [], responseBytes: 0, delayMs: 0, advanceActive: false, revision: 0 };
    fixture.intercept = async (request, target) => {
        if (target.pathname === "/api/session" && request.method() === "GET") return { json: { csrfToken: "qa-browser-local-token" } };
        if (!target.pathname.startsWith("/api/website-assessments")) return null;
        let json;
        if (request.method() === "POST" && target.pathname === "/api/website-assessments") {
            assert.equal(request.headers()["x-csrf-token"], "qa-browser-local-token", "Synthetic create must retain CSRF protection");
            const body = request.postDataJSON();
            assert.deepEqual(body, { url: "https://example.org/public/index.php" });
            fixture.posts.push(body);
            fixture.report = websiteReport("ANALYZING");
            json = { assessmentId: fixture.report.assessmentId };
        } else if (request.method() === "GET") {
            fixture.reads.push(target.pathname);
            if (target.pathname === "/api/website-assessments/examples") {
                json = { items: [{ id: "invicti", title: "Invicti PHP test site", url: "http://php.testsparker.com/", description: "Public sample; filling does not start an assessment." }] };
            } else if (target.pathname === "/api/website-assessments") {
                json = { items: fixture.report ? [fixture.report] : [] };
            } else {
                assert.equal(target.pathname, "/api/website-assessments/qa-website-completed", "Unexpected synthetic assessment request");
                assert(fixture.report, "Selected synthetic report must exist");
                if (fixture.advanceActive && fixture.report.state === "ANALYZING") {
                    fixture.revision += 1;
                    fixture.report = { ...fixture.report,
                        stageMessage: `Browser QA: analyzing intercepted evidence; update ${fixture.revision}. No provider or target request was sent.`,
                        events: [...fixture.report.events, { sequence: 10 + fixture.revision, timestamp: "2026-10-24T12:00:01Z",
                            stage: "ANALYZING", message: `Browser-local update ${fixture.revision}; no provider call.` }] };
                }
                json = fixture.report;
            }
        } else { return null; }
        fixture.responseBytes += Buffer.byteLength(JSON.stringify(json));
        if (fixture.delayMs) await new Promise(resolve => setTimeout(resolve, fixture.delayMs));
        return { json };
    };
    return fixture;
}

async function websiteValidation(page, fixture) {
    for (const value of ["not a URL", "http://127.0.0.1/", "http://192.168.1.1/", "http://[::1]/", "http://localhost/",
        "https://user:password@example.org/", "https://example.org/?token=do-not-send", "https://example.org:8443/", "javascript:alert(1)"]) {
        await page.locator("#website-url").fill(value);
        await page.locator("#website-submit").click();
        const error = page.locator("#website-url-error");
        await error.waitFor({ state: "visible" });
        assert.equal(await page.locator("#website-url").getAttribute("aria-invalid"), "true");
        assert((await page.locator("#website-url").getAttribute("aria-describedby")).split(/\s+/).includes("website-url-error"));
        assert.equal(await page.evaluate(() => document.activeElement?.id), "website-url");
        assert.equal(fixture.posts.length, 0, "Rejected public URL must not create even an intercepted assessment");
    }
}

async function refreshWebsiteKeepingFocus(page, fixture, focusId) {
    const history = page.locator("#website-history");
    if (!(await history.evaluate(element => element.open))) await history.locator(":scope > summary").press("Enter");
    fixture.delayMs = 200;
    const reads = fixture.reads.length;
    try {
        await page.locator("#website-refresh").click();
        await page.locator(`[id=${JSON.stringify(focusId)}]`).focus();
        await page.waitForTimeout(400);
        assert(fixture.reads.length > reads, "Manual history refresh must read intercepted API data");
    } finally { fixture.delayMs = 0; }
}

async function websiteDisclosureJump(page, fixture) {
    const evidenceId = "website-evidence-qa-website-completed-e1";
    const detail = page.locator(`[id=${JSON.stringify(evidenceId)}]`);
    assert.equal(await detail.evaluate(element => element.open), false, "Evidence must start closed");
    const action = page.locator("details.website-action").first();
    if (!(await action.evaluate(element => element.open))) await action.locator(":scope > summary").press("Enter");
    await action.getByRole("button", { name: "View evidence e1", exact: true }).click();
    assert(await detail.evaluate(element => element.open), "Evidence jump must reveal its recorded observation");
    assert.equal(await page.evaluate(() => document.activeElement?.id), `${evidenceId}-summary`, "Evidence jump must move keyboard focus to the revealed summary");
    await refreshWebsiteKeepingFocus(page, fixture, `${evidenceId}-summary`);
    assert(await detail.evaluate(element => element.open), "Refresh collapsed the evidence opened from a finding");
    assert.equal(await page.evaluate(() => document.activeElement?.id), `${evidenceId}-summary`, "Refresh moved focus away from linked evidence");
    await page.keyboard.press("Enter");
    assert.equal(await detail.evaluate(element => element.open), false, "Keyboard must close linked evidence");
}

async function performanceWindow(page, fixture, label) {
    const before = await page.evaluate(() => ({ ...window.__patchpilotQaPerf,
        longTasks: [...window.__patchpilotQaPerf.longTasks] }));
    const reads = fixture.reads.length;
    const bytes = fixture.responseBytes;
    await page.waitForTimeout(pollWindowMs);
    const after = await page.evaluate(() => {
        const displayed = element => {
            if (!element.getClientRects().length || getComputedStyle(element).visibility === "hidden") return false;
            for (let parent = element.parentElement; parent; parent = parent.parentElement) {
                if (parent.tagName === "DETAILS" && !parent.open && !parent.querySelector(":scope > summary")?.contains(element)) return false;
            }
            return true;
        };
        return { ...window.__patchpilotQaPerf, nodes: document.querySelectorAll("#app-main *").length,
            visibleNodes: [...document.querySelectorAll("#app-main *")].filter(displayed).length,
            heapBytes: performance.memory?.usedJSHeapSize ?? null };
    });
    performanceSamples.push({ label, windowMs: pollWindowMs, apiReads: fixture.reads.slice(reads),
        responseBytes: fixture.responseBytes - bytes, reportBytes: Buffer.byteLength(JSON.stringify(fixture.report)),
        mainReplacements: after.mainReplacements - before.mainReplacements,
        mutationRecords: after.mutationRecords - before.mutationRecords,
        longTasksMs: after.longTasks.slice(before.longTasks.length), nodes: after.nodes,
        visibleNodes: after.visibleNodes, heapBytes: after.heapBytes });
    if (["website-empty", "website-completed"].includes(label)) {
        assert.equal(fixture.reads.length - reads, 0, `${label}: idle pages must not refetch unchanged history, examples or reports`);
        assert.equal(after.mainReplacements - before.mainReplacements, 0, `${label}: idle pages must not rebuild the report DOM`);
    }
}

async function websiteSelectionRace() {
    const slow = { ...websiteReport("COMPLETED"), assessmentId: "qa-slow", url: "https://example.org/slow.php" };
    const fast = { ...websiteReport("COMPLETED"), assessmentId: "qa-fast", url: "https://example.org/fast.php",
        phpDetection: { status: "REPORTED", version: "8.3.36", explanation: "Newly selected browser QA report.", evidenceIds: ["e1"] } };
    let startedSlow;
    const slowStarted = new Promise(resolve => { startedSlow = resolve; });
    const fixture = await newPage({ intercept: async (request, target) => {
        if (request.method() !== "GET") return null;
        if (target.pathname === "/api/session") return { json: { csrfToken: "qa-race-token" } };
        if (target.pathname === "/api/website-assessments") return { json: { items: [slow, fast] } };
        if (target.pathname === "/api/website-assessments/examples") return { json: { items: [] } };
        if (target.pathname === "/api/website-assessments/qa-slow") {
            startedSlow();
            await new Promise(resolve => setTimeout(resolve, 600));
            return { json: slow };
        }
        if (target.pathname === "/api/website-assessments/qa-fast") return { json: fast };
        return null;
    } });
    try {
        await fixture.page.goto(`${origin}/dashboard#/scan/qa-slow`, { waitUntil: "domcontentloaded" });
        await Promise.race([slowStarted, new Promise((_, reject) => setTimeout(() => reject(new Error("Slow report request did not start")), 5000))]);
        await fixture.page.evaluate(() => { location.hash = "#/scan/qa-fast"; });
        await fixture.page.waitForFunction(() => document.querySelector(".website-stat--php dd")?.textContent === "PHP 8.3.36");
        await fixture.page.waitForTimeout(800);
        assert.equal(new URL(fixture.page.url()).hash, "#/scan/qa-fast");
        assert.equal(await fixture.page.locator("#website-report-heading a").getAttribute("href"), fast.url,
            "A delayed previous request must not replace the newly selected report");
        assert.equal(await fixture.page.locator(".website-stat--php dd").innerText(), "PHP 8.3.36");
        await screenshot(fixture.page, "website-selection-race");
    } finally { await fixture.context.close(); }
}

async function responsive(page, label) {
    for (const width of widths) {
        await page.setViewportSize({ width, height: 1000 });
        await page.waitForTimeout(100);
        const overflow = await page.evaluate(() => {
            const viewport = document.documentElement.clientWidth;
            const overflowing = [...document.querySelectorAll("body *")].filter(element => {
                const box = element.getBoundingClientRect();
                const style = getComputedStyle(element);
                return box.width && style.position !== "fixed" && (box.right > viewport + 1 || box.left < -1)
                    && style.visibility !== "hidden" && style.display !== "none";
            }).slice(0, 8).map(element => `${element.tagName.toLowerCase()}${element.id ? `#${element.id}` : ""}.${String(element.className).replace(/\s+/g, ".")}`);
            const narrowColumns = [...document.querySelectorAll(".run-table thead th")].filter(element => {
                if (!element.getClientRects().length || element.textContent.trim().length < 4) return false;
                const style = getComputedStyle(element);
                return element.getBoundingClientRect().width - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight) < 32;
            }).map(element => element.textContent.trim());
            const inaccessibleScroll = [...document.querySelectorAll(".table-scroll")].filter(element =>
                element.getClientRects().length && element.scrollWidth > element.clientWidth + 1
                && (element.tabIndex < 0 || !(element.getAttribute("aria-label") || element.getAttribute("aria-labelledby"))))
                .map(element => element.outerHTML.slice(0, 160));
            return { viewport, width: document.documentElement.scrollWidth, overflowing, narrowColumns, inaccessibleScroll };
        });
        assert(overflow.width <= overflow.viewport + 1,
            `${label} overflows at ${width}px: ${JSON.stringify(overflow)}`);
        assert.deepEqual(overflow.narrowColumns, [], `${label}: verification columns are unreadable at ${width}px`);
        assert.deepEqual(overflow.inaccessibleScroll, [], `${label}: scrolling tables must be named and keyboard focusable at ${width}px`);
        if (width === 320 && label.startsWith("website-")) await accessibility(page, `${label}-320`);
        await screenshot(page, `${label}-${width}`);
    }
    await page.setViewportSize({ width: 1440, height: 1000 });
}

async function accessibility(page, label) {
    const structure = await page.evaluate(() => {
        const visible = element => Boolean(element.getClientRects().length) && getComputedStyle(element).visibility !== "hidden";
        const idCounts = new Map();
        for (const element of document.querySelectorAll("[id]")) idCounts.set(element.id, (idCounts.get(element.id) || 0) + 1);
        const duplicates = [...idCounts].filter(([id, count]) => id && count > 1).map(([id]) => id);
        const unnamed = [...document.querySelectorAll("button, a[href], input:not([type=hidden]), select, textarea, summary")]
            .filter(element => visible(element) && !element.disabled).filter(element => {
                const labelled = element.getAttribute("aria-labelledby")?.split(/\s+/).map(id => document.getElementById(id)?.textContent || "").join(" ");
                const label = element.getAttribute("aria-label") || labelled || element.labels?.[0]?.textContent
                    || element.textContent || element.getAttribute("title") || (["submit", "button"].includes(element.type) ? element.value : "");
                return !label?.trim();
            }).map(element => `${element.tagName.toLowerCase()}#${element.id}`);
        return { lang: document.documentElement.lang, h1: document.querySelectorAll("h1").length,
            main: document.querySelectorAll("main").length, duplicates, unnamed };
    });
    assert(structure.lang, `${label}: document language is missing`);
    assert.equal(structure.h1, 1, `${label}: expected one h1`);
    assert.equal(structure.main, 1, `${label}: expected one main landmark`);
    assert.deepEqual(structure.duplicates, [], `${label}: duplicate IDs`);
    assert.deepEqual(structure.unnamed, [], `${label}: unnamed controls`);
    if (axeSource) {
        // DevTools evaluation keeps the application's strict script CSP intact.
        await page.evaluate(axeSource);
        const violations = await page.evaluate(async () => {
            const result = await window.axe.run(document, { runOnly: { type: "tag", values: ["wcag2a", "wcag2aa", "wcag21aa"] } });
            return result.violations.map(item => ({ id: item.id, impact: item.impact,
                nodes: item.nodes.map(node => node.target.join(" ")).slice(0, 5) }));
        });
        assert.deepEqual(violations, [], `${label}: axe WCAG violations: ${JSON.stringify(violations)}`);
    }
}

async function keyboardSkip(page) {
    await page.goto(page.url(), { waitUntil: "networkidle" });
    const route = new URL(page.url()).hash;
    await page.keyboard.press("Tab");
    const target = await page.evaluate(() => {
        const element = document.activeElement;
        return { text: element?.textContent?.trim(), href: element?.getAttribute("href") };
    });
    assert(/skip.*(main|content)/i.test(target.text || ""), `First Tab should reveal the skip link; focused ${target.text}`);
    assert(target.href?.startsWith("#"), "Skip link must target this page");
    await page.keyboard.press("Enter");
    assert.equal(await page.evaluate(() => document.activeElement?.id), target.href.slice(1), "Skip link must focus the main target");
    if (new URL(page.url()).pathname === "/dashboard") {
        await page.waitForTimeout(100);
        assert.equal(new URL(page.url()).hash, route, "Skipping to dashboard content must preserve the current assessment or lab route");
    }
}

async function mockReady(page, scenario = null) {
    const query = `?mock=1${scenario ? `&scenario=${scenario}` : ""}`;
    await page.goto(`${origin}/dashboard${query}#/fleet`, { waitUntil: "networkidle" });
    await page.locator("#registered-site-url").waitFor({ state: "visible" });
    await page.getByText(/simulated (demo data|walkthrough)|repair lab.*simulated|simulation.*no real/i).first().waitFor({ state: "visible" });
    assert.equal(new URL(page.url()).searchParams.get("mock"), "1", "Mutating QA must remain in explicit mock mode");
}

async function validateUrls(page, requests) {
    const input = page.locator("#registered-site-url");
    for (const value of ["not a URL", "https://example.com", "http://127.0.0.1:65534",
        "http://user:pass@127.0.0.1:8081", "http://127.0.0.1:8081/contact.php",
        "http://127.0.0.1:8081?debug=1", "javascript:alert(1)"]) {
        const before = requests.length;
        await input.fill(value);
        await page.locator("#assess-url").click();
        await page.waitForTimeout(100);
        const nativeInvalid = await input.evaluate(element => !element.validity.valid);
        if (!nativeInvalid) {
            const error = page.locator("[role=alert]").filter({ hasText: /registered|complete|connection|address|URL|credentials/i }).first();
            await error.waitFor({ state: "visible" });
            assert.equal(await input.getAttribute("aria-invalid"), "true", "URL field must expose invalid state");
            const errorId = await error.getAttribute("id");
            assert(errorId && (await input.getAttribute("aria-describedby") || "").split(/\s+/).includes(errorId),
                "URL error must be associated with its input");
            assert.equal(await page.evaluate(() => document.activeElement?.id), "registered-site-url", "Rejected URL must return focus to the field");
        }
        assert.equal(await page.locator("[role=dialog]:visible").count(), 0, "Rejected URL must not open assessment approval");
        const unsafe = requests.slice(before).filter(request => {
            const target = new URL(request.url);
            return target.origin !== origin || !["GET", "HEAD", "OPTIONS"].includes(request.method);
        });
        assert.deepEqual(unsafe, [], `Rejected URL caused an external request or mutation: ${value}`);
    }
    await input.fill("http://127.0.0.1:8081");
    await input.focus();
    await page.waitForTimeout(pollWindowMs);
    assert.equal(await input.inputValue(), "http://127.0.0.1:8081", "Polling must preserve typed URL");
    assert.equal(await page.evaluate(() => document.activeElement?.id), "registered-site-url", "Polling must preserve URL focus");
}

async function approvalKeyboard(page) {
    await page.locator("#registered-site-url").fill("http://127.0.0.1:8081");
    await page.locator("#assess-url").click();
    const dialog = page.locator("[role=dialog]");
    await dialog.waitFor({ state: "visible" });
    await page.locator("#approval-approve-btn:not([disabled])").waitFor();
    assert.equal(await dialog.getAttribute("aria-modal"), "true", "Approval must identify its modal scope");
    assert(await page.locator("main").evaluate(element => Boolean(element.closest("[inert]"))),
        "Background content must be inert while approval is modal");
    assert(!(await dialog.evaluate(element => Boolean(element.closest("[inert]")))), "Approval itself must remain interactive");
    await persistentDisclosure(page, "[role=dialog] details[id]");
    for (let index = 0; index < 16; index += 1) {
        await page.keyboard.press(index < 8 ? "Tab" : "Shift+Tab");
        assert(await page.evaluate(() => Boolean(document.activeElement?.closest("[role=dialog]"))), "Keyboard focus escaped approval");
    }
    await page.keyboard.press("Escape");
    await dialog.waitFor({ state: "hidden" });
    assert.equal(await page.evaluate(() => document.activeElement?.id), "assess-url", "Cancel should restore the initiating control");
}

async function persistentDisclosure(page, selector = "main details[id]") {
    const id = await page.locator(selector).evaluateAll(elements => elements.find(element => element.getClientRects().length)?.id || null);
    assert(id, "Evidence must provide a persistent native disclosure");
    const detail = page.locator(`[id=${JSON.stringify(id)}]`);
    const summary = detail.locator(":scope > summary");
    await summary.focus();
    await page.keyboard.press("Enter");
    assert(await detail.evaluate(element => element.open), "Evidence disclosure did not open from keyboard");
    const summaryId = await summary.getAttribute("id");
    assert(summaryId, "Evidence summary needs a stable ID for polling focus restoration");
    await page.waitForTimeout(pollWindowMs);
    assert(await detail.evaluate(element => element.open), "Polling collapsed expanded evidence");
    assert.equal(await page.evaluate(() => document.activeElement?.id), summaryId, "Polling moved focus away from evidence");
}

async function mockWorkflow(page, scenario = null) {
    await mockReady(page, scenario);
    await page.locator("#registered-site-url").fill("http://127.0.0.1:8081");
    await page.locator("#assess-url").click();
    await page.locator("#approval-approve-btn:not([disabled])").waitFor();
    await accessibility(page, `approval-${scenario || "success"}`);
    await responsive(page, `approval-${scenario || "success"}`);
    await page.locator("#approval-approve-btn").click();
    await page.getByRole("heading", { name: /repair progress|repair in progress|live progress/i }).waitFor({ timeout: 15000 });
    await screenshot(page, `progress-${scenario || "success"}`);
    await page.getByRole("heading", { name: /repair report|repair result|verification report/i }).waitFor({ timeout: 30000 });
    await page.waitForFunction(rollback => {
        const text = document.querySelector(".outcome-banner__title")?.textContent || "";
        return rollback ? /restored/i.test(text) && /unpatched|still vulnerable/i.test(text)
            : /patched\s*(?:&|and|\+)\s*verified|repair verified|successfully verified/i.test(text);
    }, scenario === "rollback", { timeout: 30000 });
    const text = await page.locator("main").innerText();
    if (scenario === "rollback") {
        assert(/restored/i.test(text) && /unpatched|still vulnerable/i.test(text), "Restored outcome must disclose that it remains unpatched");
    } else {
        assert(/patched\s*(?:&|and|\+)\s*verified|repair verified|successfully verified/i.test(text), "Report did not expose the successful mock outcome");
    }
    await page.getByText(/simulated (demo data|walkthrough)|repair lab.*simulated|simulation.*no real/i).first().waitFor({ state: "visible" });
    await accessibility(page, `report-${scenario || "success"}`);
    await responsive(page, `report-${scenario || "success"}`);
    await persistentDisclosure(page);
}

async function main() {
    const macChrome = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
    const executablePath = process.env.CHROME_EXECUTABLE || (fs.existsSync(macChrome) ? macChrome : undefined);
    browser = await chromium.launch({ headless: true, ...(executablePath ? { executablePath } : {}) });
    const landing = await newPage();
    try {
        await check("landing route and dashboard links", async () => {
            await landing.page.goto(`${origin}/`, { waitUntil: "networkidle" });
            await landing.page.locator('body[data-page="landing"]').waitFor();
            const open = landing.page.getByRole("link", { name: "Open dashboard", exact: true }).first();
            assert.equal(new URL(await open.getAttribute("href"), origin).pathname, "/dashboard");
            const explore = landing.page.getByRole("link", { name: "Explore repair lab simulation", exact: true }).first();
            const target = new URL(await explore.getAttribute("href"), origin);
            assert.equal(target.pathname, "/dashboard");
            assert.equal(target.searchParams.get("mock"), "1");
            assert(!landing.requests.some(request => new URL(request.url).pathname.startsWith("/api/")), "Landing must not initialize the repair API");
            await accessibility(landing.page, "landing");
            await responsive(landing.page, "landing");
        }, landing.page);
        await check("landing keyboard skip link", () => keyboardSkip(landing.page), landing.page);
        await check("landing FAQ keyboard disclosure", async () => {
            const disclosure = landing.page.locator("#faq details").first();
            await disclosure.locator(":scope > summary").focus();
            await landing.page.keyboard.press("Enter");
            assert(await disclosure.evaluate(element => element.open), "FAQ must open with Enter");
            await landing.page.keyboard.press("Enter");
            assert(!(await disclosure.evaluate(element => element.open)), "FAQ must close with Enter");
        }, landing.page);
        await check("walkthrough navigation", async () => {
            await landing.page.goto(`${origin}/`, { waitUntil: "networkidle" });
            const lab = landing.page.locator("#faq details").filter({ hasText: "Where is the repair lab?" });
            if (await lab.count() && !(await lab.evaluate(element => element.open))) await lab.locator(":scope > summary").press("Enter");
            await landing.page.getByRole("link", { name: "Explore repair lab simulation", exact: true }).first().click();
            await landing.page.locator("#registered-site-url").waitFor();
            assert.equal(new URL(landing.page.url()).pathname, "/dashboard");
            assert.equal(new URL(landing.page.url()).searchParams.get("mock"), "1");
        }, landing.page);
    } finally { await landing.context.close(); }

    const animatedLanding = await newPage({ reducedMotion: "no-preference" });
    try {
        await check("landing illustration completes its finite introduction", async () => {
            await animatedLanding.page.goto(`${origin}/`, { waitUntil: "networkidle" });
            await animatedLanding.page.evaluate(async () => {
                await Promise.race([Promise.all(document.getAnimations().map(animation => animation.finished.catch(() => {}))),
                    new Promise(resolve => setTimeout(resolve, 2000))]);
            });
            const running = await animatedLanding.page.evaluate(() => document.getAnimations()
                .filter(animation => animation.playState === "running").map(animation => animation.animationName || "unnamed animation"));
            assert.deepEqual(running, [], "Landing should settle without infinite animation");
            for (const selector of [".iso-browser", ".iso-shield", ".iso-php"]) {
                assert(await animatedLanding.page.locator(selector).isVisible(), `${selector} must remain visible after its introduction`);
            }
            await screenshot(animatedLanding.page, "landing-motion-finished-1440");
            await animatedLanding.page.setViewportSize({ width: 320, height: 1000 });
            await animatedLanding.page.waitForTimeout(100);
            assert(await animatedLanding.page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1),
                "Finished mobile illustration must not overflow the page");
            await screenshot(animatedLanding.page, "landing-motion-finished-320");
            assert(!animatedLanding.requests.some(request => new URL(request.url).pathname.startsWith("/api/")), "Landing illustration must not initialize the API");
        }, animatedLanding.page);
    } finally { await animatedLanding.context.close(); }

    const websiteFixture = websiteInterception();
    const website = await newPage({ intercept: websiteFixture.intercept });
    try {
        await check("default public website view and fill-only sample", async () => {
            await website.page.goto(`${origin}/dashboard`, { waitUntil: "networkidle" });
            await website.page.getByRole("heading", { name: "A safer site starts here.", exact: true }).waitFor();
            const input = website.page.locator("#website-url");
            await input.waitFor({ state: "visible" });
            assert.equal(await website.page.locator("#registered-site-url").count(), 0,
                "The default task must not be the preconfigured fixture form");
            assert.equal(await website.page.locator(".aside").isVisible(), false,
                "Repair preparation controls must stay separate from website assessment");
            const before = website.requests.length;
            await website.page.getByRole("button", { name: "Try the PHP demo", exact: true }).click();
            assert.equal(await input.inputValue(), "http://php.testsparker.com/", "Public example should fill the real URL form");
            assert.equal(await website.page.evaluate(() => document.activeElement?.id), "website-url", "Sample selection should focus the URL field");
            await website.page.waitForTimeout(pollWindowMs);
            assert.equal(await input.inputValue(), "http://php.testsparker.com/", "Website draft must survive polling");
            assert.equal(await website.page.evaluate(() => document.activeElement?.id), "website-url", "Website draft focus must survive polling");
            assert(!website.requests.slice(before).some(request => !["GET", "HEAD", "OPTIONS"].includes(request.method)),
                "A sample button must not start a scan or mutation");
            assert(!website.requests.some(request => /^\/api\/(health|sites|prepare|runs)(?:\/|$)/.test(new URL(request.url).pathname)),
                "Public assessment must not depend on fixture readiness");
            await input.evaluate(element => { window.__qaUrlNode = element; });
            await input.fill("https://example.org/");
            await input.pressSequentially("guide");
            assert(await input.evaluate(element => element === window.__qaUrlNode), "Typing must retain the actual URL input node");
            assert.equal(await input.inputValue(), "https://example.org/guide", "Typing must retain all entered characters");
            await performanceWindow(website.page, websiteFixture, "website-empty");
            await accessibility(website.page, "website-default");
            await responsive(website.page, "website-default");
            await keyboardSkip(website.page);
        }, website.page);
        await check("public URL validation blocks external requests and creation", () => websiteValidation(website.page, websiteFixture), website.page);
        await check("intercepted active website assessment is compact and responsive", async () => {
            await website.page.locator("#website-url").fill("https://example.org/public/index.php");
            await website.page.locator("#website-submit").click();
            await website.page.waitForFunction(() => location.hash.includes("qa-website-completed")
                && document.getElementById("website-agent-message")?.textContent.includes("Browser QA: analyzing"));
            assert.equal(websiteFixture.posts.length, 1, "Exactly one browser-local assessment should be created");
            assert(await website.page.locator("#website-submit").isDisabled(), "Active assessment must block accidental duplicate submission");
            assert(await website.page.evaluate(() => matchMedia("(prefers-reduced-motion: reduce)").matches), "QA must exercise reduced motion");
            const animations = await website.page.locator(".website-spinner").evaluateAll(elements => elements.map(element => getComputedStyle(element).animationName));
            assert(animations.every(name => name === "none"), "Progress animation must respect reduced motion");
            const activity = website.page.locator(".website-progress .website-event-list");
            if (await activity.count()) assert.equal(await activity.first().isVisible(), false, "Detailed active activity should start collapsed");
            await accessibility(website.page, "website-active");
            await responsive(website.page, "website-active");
            websiteFixture.advanceActive = true;
            await persistentDisclosure(website.page, ".website-progress details[id]");
            await website.page.keyboard.press("Enter");
            await performanceWindow(website.page, websiteFixture, "website-active");
        }, website.page);
        await check("completed website report uses closed evidence and recommendation disclosures", async () => {
            websiteFixture.report = websiteReport("COMPLETED");
            await website.page.getByText("Synthetic browser QA guidance: review the evidence before any server-side change.", { exact: true }).waitFor();
            assert(!(await website.page.locator("#website-submit").isDisabled()), "Completion should permit another deliberate assessment");
            const evidenceDetails = website.page.locator(".website-evidence-card");
            assert.equal(await evidenceDetails.count(), 7, "All response/evidence records must remain available");
            assert.deepEqual(await evidenceDetails.evaluateAll(elements => elements.filter(element => element.open).map(element => element.id)), [],
                "HTTP metadata and individual evidence should start closed");
            const recommendations = website.page.locator("details.website-action");
            assert.equal(await recommendations.count(), 3, "All actionable recommendations must remain available as disclosures");
            assert.deepEqual(await recommendations.evaluateAll(elements => elements.filter(element => element.open).map(element => element.id)), [],
                "Code and configuration recommendations should start collapsed");
            const another = website.page.locator("#website-new-assessment");
            assert.equal(await another.evaluate(element => element.open), false, "The completed report should keep another URL form collapsed");
            assert(await another.evaluate(element => Boolean(document.querySelector(".website-report")
                .compareDocumentPosition(element) & Node.DOCUMENT_POSITION_FOLLOWING)), "The assessment result must precede the next-URL form");
            assert.equal(await website.page.locator("main .outcome-banner").count(), 0, "Assessment must not be presented as a verified repair");
            await accessibility(website.page, "website-completed");
            await responsive(website.page, "website-completed");
            await performanceWindow(website.page, websiteFixture, "website-completed");
        }, website.page);
        await check("website finding evidence jumps retain focus and disclosure state", () => websiteDisclosureJump(website.page, websiteFixture), website.page);
        await check("website remediation retains keyboard reading state and escapes untrusted text", async () => {
            const recommendation = website.page.locator("details.website-action").first();
            const summary = recommendation.locator(":scope > summary");
            const id = await recommendation.getAttribute("id");
            assert(id, "Recommendations need stable disclosure IDs");
            await summary.focus();
            if (!(await recommendation.evaluate(element => element.open))) await website.page.keyboard.press("Enter");
            assert(await recommendation.evaluate(element => element.open), "Recommendation must open from keyboard");
            const summaryId = await summary.getAttribute("id");
            assert(summaryId, "Recommendation summaries need persistent focus IDs");
            await refreshWebsiteKeepingFocus(website.page, websiteFixture, summaryId);
            assert(await recommendation.evaluate(element => element.open), "Polling collapsed the recommendation being read");
            assert.equal(await website.page.evaluate(() => document.activeElement?.id), summaryId, "Polling moved recommendation focus");
            const maliciousEvidence = website.page.locator("#website-evidence-qa-website-completed-e6");
            await maliciousEvidence.locator(":scope > summary").press("Enter");
            assert((await maliciousEvidence.innerText()).includes('<img src=x onerror="globalThis.__patchpilotXss=1">'), "Evidence must preserve literal untrusted text");
            const codeRecommendation = website.page.locator("details.website-action").nth(2);
            await codeRecommendation.locator(":scope > summary").press("Enter");
            await codeRecommendation.locator(".website-code-details > summary").press("Enter");
            assert((await codeRecommendation.locator("code").innerText()).includes("<script>globalThis.__patchpilotXss=1</script>"), "Suggested code must be text, not executable markup");
            assert.equal(await website.page.evaluate(() => Boolean(window.__patchpilotXss)), false, "Untrusted report text executed");
            assert.equal(await website.page.locator('main img, main script, main a[href^="javascript:"]').count(), 0,
                "Untrusted evidence/references/code must not create active elements");
            await accessibility(website.page, "website-expanded");
            await responsive(website.page, "website-expanded");
        }, website.page);
        await check("another website draft preserves its field, focus and report", async () => {
            await website.page.locator("#website-new-assessment-summary").press("Enter");
            const input = website.page.locator("#website-url");
            await input.evaluate(element => { window.__qaReportUrlNode = element; });
            await input.fill("https://example.org/draft");
            await input.pressSequentially("-page.php");
            await website.page.waitForTimeout(pollWindowMs);
            assert.equal(await input.inputValue(), "https://example.org/draft-page.php", "A next-assessment draft must survive idle time");
            assert(await input.evaluate(element => element === window.__qaReportUrlNode), "Typing must retain the report's URL field node");
            assert.equal(await website.page.evaluate(() => document.activeElement?.id), "website-url", "Drafting must retain keyboard focus");
            assert.equal(await website.page.locator("#website-report-heading a").getAttribute("href"), "https://example.org/public/index.php",
                "Typing another URL must not change the recorded report's source");
            assert.equal(websiteFixture.posts.length, 1, "Drafting another URL must not start an assessment");
            await website.page.locator("#website-new-assessment-summary").press("Enter");
        }, website.page);
        await check("failed website assessment retains partial observations without fabricated analysis", async () => {
            websiteFixture.report = websiteReport("FAILED");
            await website.page.reload({ waitUntil: "networkidle" });
            await website.page.getByRole("alert").filter({ hasText: "Browser QA: provider unavailable" }).waitFor({ timeout: 15000 });
            await website.page.getByText(/AI recommendations aren't available/i).waitFor();
            assert.equal(await website.page.locator(".website-evidence-card").count(), 7, "Failure must retain collected HTTP evidence");
            assert.equal(await website.page.locator("details.website-action").count(), 0, "Failure must not substitute precomputed model advice");
            assert.equal(await website.page.locator(".website-stat--php dd").innerText(), "PHP 5.2.6", "Partial observed PHP evidence must remain readable");
            assert(!(await website.page.locator("#website-submit").isDisabled()), "A failed assessment must not leave submission permanently disabled");
            await accessibility(website.page, "website-failed");
            await responsive(website.page, "website-failed");
        }, website.page);
    } finally { await website.context.close(); }

    await check("website report navigation ignores a delayed previous selection", websiteSelectionRace);

    const compatibility = await newPage();
    try {
        await check("legacy query and fleet hash redirects", async () => {
            for (const suffix of ["/?mock=1", "/#/fleet"]) {
                await compatibility.page.goto(`${origin}${suffix}`, { waitUntil: "networkidle" });
                await compatibility.page.waitForURL(url => url.pathname === "/dashboard");
                const redirected = new URL(compatibility.page.url());
                if (suffix.includes("mock")) assert.equal(redirected.searchParams.get("mock"), "1");
                if (suffix.includes("#/fleet")) assert.equal(redirected.hash, "#/fleet");
            }
        }, compatibility.page);
    } finally { await compatibility.context.close(); }

    const dashboard = await newPage();
    try {
        await check("dashboard mock routing, responsive layout, and semantics", async () => {
            await mockReady(dashboard.page);
            await accessibility(dashboard.page, "dashboard");
            await responsive(dashboard.page, "dashboard");
        }, dashboard.page);
        await check("dashboard keyboard skip link", () => keyboardSkip(dashboard.page), dashboard.page);
        await check("dashboard navigation keyboard and route focus", async () => {
            const metrics = dashboard.page.locator('#app-nav a[href="#/metrics"]');
            await metrics.press("Enter");
            await dashboard.page.waitForFunction(() => location.hash === "#/metrics");
            await dashboard.page.waitForFunction(() => document.activeElement === document.querySelector("main"));
            assert.equal(await metrics.getAttribute("aria-current"), "page", "Current navigation destination needs aria-current");
            await dashboard.page.locator('#app-nav a[href="#/fleet"]').press("Enter");
            await dashboard.page.waitForFunction(() => location.hash === "#/fleet");
            await dashboard.page.waitForFunction(() => document.activeElement === document.querySelector("main"));
        }, dashboard.page);
        await check("workspace checkbox selection persists through polling", async () => {
            const toggle = dashboard.page.locator("#demo-controls-toggle");
            if (await toggle.getAttribute("aria-expanded") !== "true") await toggle.click();
            const checkbox = dashboard.page.locator("#demo-clear-memory");
            await checkbox.check();
            await dashboard.page.waitForTimeout(pollWindowMs);
            assert(await checkbox.isChecked(), "Polling reset the clear-recipe checkbox selection");
            await checkbox.uncheck();
            await toggle.click();
        }, dashboard.page);
        await check("URL validation prevents requests and preserves input focus", () => validateUrls(dashboard.page, dashboard.requests), dashboard.page);
        await check("approval keyboard trap, cancel, and focus restoration", () => approvalKeyboard(dashboard.page), dashboard.page);
        await check("approval body scroll position persists through polling", async () => {
            await dashboard.page.setViewportSize({ width: 768, height: 360 });
            const dialog = dashboard.page.locator("[role=dialog]");
            try {
                await dashboard.page.locator("#registered-site-url").fill("http://127.0.0.1:8082");
                await dashboard.page.locator("#assess-url").click();
                await dashboard.page.locator("#approval-approve-btn:not([disabled])").waitFor();
                const summary = dialog.locator("#approval-demo-config-summary");
                await summary.press("Enter");
                const body = dialog.locator(".drawer__body[id]");
                const id = await body.getAttribute("id");
                assert(id, "Approval body needs a stable scroll ID");
                assert(await body.evaluate(element => element.scrollHeight > element.clientHeight), "Short-viewport approval should expose a scrollable body");
                await body.hover({ position: { x: 20, y: 30 } });
                await dashboard.page.mouse.wheel(0, 120);
                await dashboard.page.waitForFunction(bodyId => document.getElementById(bodyId)?.scrollTop > 0, id);
                await dashboard.page.waitForTimeout(250);
                const top = await body.evaluate(element => element.scrollTop);
                const focus = await dashboard.page.evaluate(() => document.activeElement?.id);
                await dashboard.page.waitForTimeout(pollWindowMs);
                assert(Math.abs(await body.evaluate(element => element.scrollTop) - top) <= 1, "Polling reset the approval body's reading position");
                assert.equal(await dashboard.page.evaluate(() => document.activeElement?.id), focus, "Polling moved approval focus");
                await screenshot(dashboard.page, "approval-scroll-persistence");
            } finally {
                if (await dialog.isVisible()) await dashboard.page.keyboard.press("Escape");
                await dashboard.page.setViewportSize({ width: 1440, height: 1000 });
            }
        }, dashboard.page);
        await check("mock assessment to approval, progress, and report", () => mockWorkflow(dashboard.page), dashboard.page);
        await check("mobile evidence tables support keyboard scrolling", async () => {
            await dashboard.page.setViewportSize({ width: 320, height: 1000 });
            const region = dashboard.page.locator(".table-scroll").first();
            const id = await region.getAttribute("id");
            assert(id, "Keyboard-scroll region needs a stable focus ID");
            assert(await region.evaluate(element => element.scrollWidth > element.clientWidth), "Mobile evidence should scroll inside its named region");
            await region.press("ArrowRight");
            await dashboard.page.waitForFunction(regionId => document.getElementById(regionId)?.scrollLeft > 0, id);
            await dashboard.page.waitForTimeout(250);
            const left = await region.evaluate(element => element.scrollLeft);
            await dashboard.page.waitForTimeout(pollWindowMs);
            assert(Math.abs(await region.evaluate(element => element.scrollLeft) - left) <= 1, "Polling reset the evidence table's horizontal reading position");
            assert.equal(await dashboard.page.evaluate(() => document.activeElement?.id), id, "Keyboard scrolling should retain region focus");
            await screenshot(dashboard.page, "report-mobile-keyboard-scroll");
            await dashboard.page.setViewportSize({ width: 1440, height: 1000 });
        }, dashboard.page);
        await check("manual activity-log scroll persists through polling", async () => {
            await dashboard.page.setViewportSize({ width: 320, height: 700 });
            try {
                // A second local mock run gives the bounded feed enough real
                // playback entries to scroll; do not inject synthetic DOM rows.
                await dashboard.page.locator('#app-nav a[href="#/fleet"]').press("Enter");
                await dashboard.page.locator("#registered-site-url").fill("http://127.0.0.1:8083");
                await dashboard.page.locator("#assess-url").click();
                await dashboard.page.locator("#approval-approve-btn:not([disabled])").waitFor();
                await dashboard.page.locator("#approval-approve-btn").click();
                await dashboard.page.waitForFunction(() =>
                    /Oak Street/.test(document.querySelector("main h1")?.textContent || "")
                    && /patched\s*(?:&|and|\+)\s*verified/i.test(document.querySelector(".outcome-banner__title")?.textContent || ""),
                null, { timeout: 30000 });
                await dashboard.page.locator('#app-nav a[href="#/events"]').press("Enter");
                await dashboard.page.waitForFunction(() => location.hash === "#/events");
                const autoScroll = dashboard.page.locator("#event-log-auto-scroll");
                await autoScroll.uncheck();
                const region = dashboard.page.locator("#event-log-scroll-region");
                assert(await region.evaluate(element => element.scrollHeight > element.clientHeight), "Activity log must provide a bounded scroll region");
                await region.press("Home");
                await region.press("ArrowDown");
                await dashboard.page.waitForFunction(() => document.getElementById("event-log-scroll-region")?.scrollTop > 0);
                await dashboard.page.waitForTimeout(250);
                const top = await region.evaluate(element => element.scrollTop);
                await dashboard.page.waitForTimeout(pollWindowMs);
                assert(Math.abs(await region.evaluate(element => element.scrollTop) - top) <= 1, "Polling reset the manually positioned activity log");
                assert.equal(await dashboard.page.evaluate(() => document.activeElement?.id), "event-log-scroll-region", "Polling moved activity-log focus");
                assert(!(await autoScroll.isChecked()), "Polling reset the manual-scroll setting");
                await screenshot(dashboard.page, "activity-manual-scroll-persistence");
            } finally { await dashboard.page.setViewportSize({ width: 1440, height: 1000 }); }
        }, dashboard.page);
    } finally { await dashboard.context.close(); }

    const recovery = await newPage();
    try {
        await check("mock restoration report stays explicitly unpatched", () => mockWorkflow(recovery.page, "rollback"), recovery.page);
    } finally { await recovery.context.close(); }

    await check("no external requests or real HTTP mutations", async () => {
        assert.deepEqual(externalRequests, [], "UI attempted requests outside the local controller");
        assert.deepEqual(blockedWrites, [], "UI attempted real HTTP mutations despite mock-only testing");
    });
    await check("browser console and page errors", async () => {
        assert.deepEqual(pageErrors, [], "Uncaught browser errors");
        assert.deepEqual(consoleErrors, [], "Browser console errors");
    });
    const failed = results.filter(result => !result.passed);
    console.log(JSON.stringify({ url: origin, passed: results.length - failed.length, failed: failed.length,
        axe: axeSource ? "enabled" : "optional module unavailable; semantic checks ran", screenshots,
        interceptedWrites, performanceSamples, results }, null, 2));
    process.exitCode = failed.length ? 1 : 0;
}

main().catch(error => {
    console.error(`UI QA aborted: ${error.stack || error}`);
    process.exitCode = 1;
}).finally(async () => { if (browser) await browser.close(); });
