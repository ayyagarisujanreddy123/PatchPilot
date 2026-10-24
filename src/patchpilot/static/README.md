# PatchPilot interface

Plain HTML, CSS, and JavaScript ES modules; no frontend build step. FastAPI serves
the product landing page at `/` and the workspace at `/dashboard`. The default
task assesses a public website URL using fresh HTTP evidence and Anthropic guidance.
The separate Repair lab operates registered local PHP fixtures.

## Structure

| File | Responsibility |
| --- | --- |
| `landing.html`, `landing.css`, `js/landing.js` | Product story, illustrative preview, workflow, FAQ, legacy-link redirects |
| `index.html` | Dashboard landmarks and module entry |
| `design.css` | Shared tokens, typography, controls, focus indicators |
| `styles.css` | Workspace layout, site records, review, progress, evidence |
| `js/main.js`, `js/state.js` | Navigation, polling, orchestration, preserved UI state |
| `js/api.js`, `js/live.js` | Real resource API and evidence normalization |
| `js/icons.js`, `js/components/` | Code-native icons and actionable readiness |
| `js/views/` | Overview, site records, review, reports, activity, operator controls |
| `js/mock.js` | Explicit simulated playback only |

## User flow

1. Enter a public URL or choose **Try the PHP demo**, then **Assess website**.
2. Watch the current real collection/Anthropic message; expand activity if needed.
3. Review the compact overview and **What to fix first**. Each **Review fix** row
   opens its steps; **View suggested code** reveals code separately.
4. Use **All findings** or **View technical evidence** for confidence, supporting
   observations, provenance, and coverage. Evidence links open the right record.
5. **Check again** collects fresh evidence. **Check another website** opens the
   URL form below the report. No suggested change is applied automatically.

Idle/completed views stop polling. Active refreshes publish one store update and
skip unchanged reports. Typing retains the input node; disclosures and focus
survive updates. CSS depth/finite motion use no animation/3D dependencies and
honor reduced motion.

## Repair lab flow

1. Select **Open dashboard**. The header distinguishes real fixtures from simulation.
2. Follow readiness guidance. **Prepare demo sites** sets up the owned local fleet.
3. Enter a registered URL, select a site's URL to fill the form, or use **Assess all sites**.
4. Review actual observations, proposed changes, required checks, and exact scope.
5. Approve the repair, or Cancel. No repair starts merely from typing a URL.
6. Follow **Repair progress** and inspect **Repair report**. Final checks lead;
   earlier failures remain visible and technical evidence is available in disclosures.

Overview filters describe current site state. Historical reports survive resets.
**Workspace controls → Reset fleet** asks for confirmation and can clear recipe
memory. Simulated fault controls appear only in mock mode. Unsupported real
metrics/recipe browsing are not offered as primary workspace tasks.

Mutation requests retain the backend session, CSRF token, exact assessment scope,
approval ID, and stable idempotency key. URL entry never triggers requests to the
entered host. API paths and the controller's safety gates are unchanged.

## Preview and verification

Use FastAPI for the complete landing/dashboard navigation. Open
`/dashboard?mock=1#/fleet` for a labeled walkthrough; add `&scenario=rollback` or
`&scenario=restorefail` for simulated recovery outcomes. Old root mock/hash URLs
redirect to the dashboard. Landing section anchors remain on the product page.

For a dashboard-only static preview, run from the repository root:

```bash
python3 -m http.server 8876 --directory src/patchpilot
```

Open `http://127.0.0.1:8876/static/index.html?mock=1#/fleet`. Full product navigation
requires the FastAPI routes.

Run deterministic interface checks:

```bash
node src/patchpilot/static/scripts/verify-api.mjs
node src/patchpilot/static/scripts/verify-website.mjs
node src/patchpilot/static/scripts/verify-mock.mjs
```

The browser harness uses Playwright, optionally with axe-core, installed outside
the repository. For example:

```bash
npm install --prefix /tmp/patchpilot-ui-tools playwright axe-core
PLAYWRIGHT_MODULE=/tmp/patchpilot-ui-tools/node_modules/playwright \
AXE_MODULE=/tmp/patchpilot-ui-tools/node_modules/axe-core \
PATCHPILOT_URL=http://127.0.0.1:8765 \
node scripts/verify-ui.cjs
```

Installed macOS Chrome is detected; elsewhere set `CHROME_EXECUTABLE` or install
Playwright Chromium. `PATCHPILOT_SCREENSHOTS=var/ui-qa` saves optional screenshots.
The harness blocks external requests and live HTTP writes. Website API responses
are intercepted locally; lab mutations use JS simulation. It checks website
states, disclosures, evidence links, idle requests/rendering, routing, keyboard
focus, URL errors, responsive layouts, lab dialogs/recovery, and polling persistence.

See [the design guide](../../../docs/design/interface.md) for the HCI rationale.
