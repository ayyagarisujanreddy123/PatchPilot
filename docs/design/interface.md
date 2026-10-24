# PatchPilot interface design

## Direction and screen responsibilities

[GitNimble](https://gitnimble.com/) informed the restrained palette, editorial
typography, generous spacing, and product-first presentation. PatchPilot uses its
own copy, code-native illustration, branding, and task layout. No reference
artwork, customer claims, or performance figures are copied.

The landing page (`/`) introduces fresh public HTTP assessment and gives one primary
next step: **Open dashboard**. The product illustration is labeled illustrative.
The secondary **Explore repair lab simulation** link opens the separate local-lab
walkthrough; it is not a public-website result or fallback.

The dashboard's default task is **Website assessment** at `/dashboard` (`#/scan`).
Its empty state has one URL action and a small CSS 3D illustration. During a job,
the real current collection/Anthropic message leads. Results show a compact
finding/PHP/fix overview and prioritized **Review fix** rows. Steps and code open
on demand. All findings, activity, evidence, provenance, and coverage start
collapsed; **Check another website** moves the URL form below the report. Public
samples fill the form without starting a job or loading precomputed findings.

**Repair lab** (`#/fleet`) and **Lab activity** (`#/events`) are secondary navigation
entries. The lab retains registered local targets, Docker preparation, exact-scope
approval, staging/live verification, and recovery. Explicit `?mock=1#/fleet` playback
stays labeled simulated. Existing repair run and mock deep links remain supported.

## HCI decisions

The implementation applies [Nielsen's usability heuristics](https://www.nngroup.com/articles/ten-usability-heuristics/)
through concrete interaction rules:

| Principle | Implemented behavior |
| --- | --- |
| Visible system status | Website collection and Anthropic analysis have distinct labels. Activity and generation counts come from actual server/provider events and timestamps, without fabricated percentages. |
| User control | Starting public assessment is explicit. Suggested fixes require review and server/source access. The separate lab names the exact scope before repair approval and supports cancel. |
| Error prevention | Website URL shape/private-destination checks run before submission, with authoritative destination/redirect validation on the server. Lab repair remains bound to registered targets and owner approval. |
| Recognition | The public sample fills the URL field. Findings open their evidence by ID. PHP signals explicitly distinguish reported, inferred, and unknown. |
| Consistency | Shared color, spacing, control, icon, and status tokens serve both screens. Ordinary navigation links expose their current location. |
| Minimalism | One public URL action leads the default workspace. Technical observations and provenance use native disclosures. Failures and partial evidence remain visible. |

Keyboard focus follows the [W3C focus-visible guidance](https://www.w3.org/WAI/WCAG22/Understanding/focus-visible.html).
Polling preserves drafts, cursor selection, disclosure state, focus, and reading
positions. Evidence links open and focus their corresponding record. Native FAQ
and evidence disclosures support keyboard operation. Statuses include text alongside
color, and reduced-motion preferences suppress animation.

The lab's modal approval makes backgrounds inert, traps focus, and returns focus
to the invoking control on cancel. Those controls are hidden from the public
assessment task, which needs no Docker preparation or repair approval.

## Evidence and analysis boundaries

**Ready to review** describes completed collection and analysis, not a verified patch
or a declaration of website safety. Public PHP headers are reported signals;
installed package/backport status and source-level vulnerabilities need additional
access. Configuration observations retain severity, confidence, references, and
evidence links.

The **Live agent activity** panel shows recorded collection and Anthropic events.
During generation, actual stream character counts provide activity feedback.
Recommendations/code appear only after the structured response is validated.
**Analysis provenance** retains the returned model ID, provider message ID, and
token usage. Suggested code is rendered as text, with an explicit copy action,
and never executed by the UI.

A network/provider failure remains `FAILED` and retains available observations.
The UI does not substitute fixture evidence, saved examples, simulated analysis,
or an invented security success. Missing PHP/version evidence stays `UNKNOWN`.

## Components and verification

`design.css` owns shared foundations. `styles.css` owns the workspace;
`landing.css` owns the public page. Website view modules separate report/progress,
HTTP evidence, findings, and Anthropic guidance. Existing modules retain lab
readiness, site records, approval, progress, and verification. All assets remain
local, with no frontend framework or build dependency. System fonts and CSS
perspective avoid downloaded 3D/font packages. Idle and completed website views
stop polling. Active refreshes publish one coherent state update and skip unchanged
reports; typing updates the draft without rebuilding the input.

`src/patchpilot/static/scripts/verify-website.mjs` checks public URL boundaries,
session/CSRF handling, fill-only samples, unknown PHP, and partial-failure retention
using a fetch test double. It makes no live target or Anthropic requests.

`scripts/verify-ui.cjs` checks landing/deep-link routes, the default public form,
fill-only sample behavior, keyboard/modal behavior, 320/768/1024/1440px layouts,
simulated lab success/restoration, and polling persistence. With axe-core installed,
it also checks WCAG A/AA rules. The guarded harness blocks external requests and
live HTTP mutations, so it cannot start a real website scan, model call, or lab repair.
Website state tests fulfill synthetic API responses locally, including creation;
these intercepted requests never reach the controller or provider.
Automated checks do not establish complete accessibility conformance or replace
usability testing with participants.

## Recorded evidence and historical screens

The focused redesign passed 28 guarded browser checks on 2026-10-24, with axe
enabled and no reported violations, console/page errors, external requests, or
forwarded HTTP writes. Website state tests used locally intercepted responses;
they did not start a live assessment. Empty and completed views made zero API
reads and zero main-view replacements during 4.5-second idle windows. A changing
active test report made four report-only reads and four coherent renders, with
no measured tasks over 50 ms. Layouts, motion preferences, nested evidence links,
disclosure/focus preservation, and the existing lab regressions passed.

The [demo guide](../demo/demo-script.md#recorded-live-website-acceptance) records the
2026-10-24 browser-driven assessment of `http://php.testsparker.com/`: fresh HTTP
200 evidence, six findings, three validated Anthropic recommendations, actual
stream updates, and returned provider metadata. That record is separate from the
guarded/test-double browser checks and from deployment-repair acceptance.

Current interface screenshots:

[Focused dashboard](screens/focused-dashboard.png) ·
[Mobile dashboard](screens/focused-mobile.png) ·
[Landing page](screens/focused-landing.png)

The following screenshots document the earlier local repair workspace:

[Earlier landing page](screens/landing.png) ·
[Repair-lab overview](screens/dashboard.png) ·
[Repair-lab mobile overview](screens/dashboard-mobile.png) ·
[Local fixture assessment](screens/assessment.png) ·
[Historical repair evidence](screens/report.png)

The local assessment screenshot shows PHP 8.3.35. The repair report carries a
historical-result notice; it does not describe the new public URL assessment or
prove a current remote deployment was patched.

The previous guarded harness passed 19 checks on 2026-10-24, including the default
public form, sample fill-only behavior, retained website draft/focus, keyboard skip,
and 320/768/1024/1440px layout/accessibility checks, alongside all retained lab
workflows. Axe was enabled and reported no tested WCAG A/AA violations. Console
and page errors, external requests, and HTTP writes were empty. The harness did
not start a real public assessment or Anthropic request.

The earlier repair-lab interface milestone passed 18 guarded browser checks at
320/768/1024/1440px on 2026-10-24, with no reported axe WCAG 2/2.1 A/AA violations,
console errors, external requests, or HTTP writes. That historical result predates
the default public website flow and is retained here as historical context.
