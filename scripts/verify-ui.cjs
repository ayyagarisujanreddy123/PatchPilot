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
 * All workflow mutations use ?mock=1; the network guard blocks every HTTP write.
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

async function newPage() {
    const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, reducedMotion: "reduce" });
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
    await page.keyboard.press("Tab");
    const target = await page.evaluate(() => {
        const element = document.activeElement;
        return { text: element?.textContent?.trim(), href: element?.getAttribute("href") };
    });
    assert(/skip.*(main|content)/i.test(target.text || ""), `First Tab should reveal the skip link; focused ${target.text}`);
    assert(target.href?.startsWith("#"), "Skip link must target this page");
    await page.keyboard.press("Enter");
    assert.equal(await page.evaluate(() => document.activeElement?.id), target.href.slice(1), "Skip link must focus the main target");
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
            await landing.page.getByRole("link", { name: "Explore repair lab simulation", exact: true }).first().click();
            await landing.page.locator("#registered-site-url").waitFor();
            assert.equal(new URL(landing.page.url()).pathname, "/dashboard");
            assert.equal(new URL(landing.page.url()).searchParams.get("mock"), "1");
        }, landing.page);
    } finally { await landing.context.close(); }

    const website = await newPage();
    try {
        await check("default public website view and fill-only sample", async () => {
            await website.page.goto(`${origin}/dashboard`, { waitUntil: "networkidle" });
            await website.page.getByRole("heading", { name: "Website assessment", exact: true }).waitFor();
            const input = website.page.locator("#website-url");
            await input.waitFor({ state: "visible" });
            assert.equal(await website.page.locator("#registered-site-url").count(), 0,
                "The default task must not be the preconfigured fixture form");
            assert.equal(await website.page.locator(".aside").isVisible(), false,
                "Repair preparation controls must stay separate from website assessment");
            const before = website.requests.length;
            await website.page.getByRole("button", { name: "Invicti PHP test site", exact: true }).click();
            assert.equal(await input.inputValue(), "http://php.testsparker.com/", "Public example should fill the real URL form");
            assert.equal(await website.page.evaluate(() => document.activeElement?.id), "website-url", "Sample selection should focus the URL field");
            await website.page.waitForTimeout(pollWindowMs);
            assert.equal(await input.inputValue(), "http://php.testsparker.com/", "Website draft must survive polling");
            assert.equal(await website.page.evaluate(() => document.activeElement?.id), "website-url", "Website draft focus must survive polling");
            assert(!website.requests.slice(before).some(request => !["GET", "HEAD", "OPTIONS"].includes(request.method)),
                "A sample button must not start a scan or mutation");
            assert(!website.requests.some(request => /^\/api\/(health|sites|prepare|runs)(?:\/|$)/.test(new URL(request.url).pathname)),
                "Public assessment must not depend on fixture readiness");
            await accessibility(website.page, "website-default");
            await responsive(website.page, "website-default");
            await keyboardSkip(website.page);
        }, website.page);
    } finally { await website.context.close(); }

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
        axe: axeSource ? "enabled" : "optional module unavailable; semantic checks ran", screenshots, results }, null, 2));
    process.exitCode = failed.length ? 1 : 0;
}

main().catch(error => {
    console.error(`UI QA aborted: ${error.stack || error}`);
    process.exitCode = 1;
}).finally(async () => { if (browser) await browser.close(); });
