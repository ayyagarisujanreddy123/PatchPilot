# PatchPilot interface design

## Direction and screen responsibilities

[GitNimble](https://gitnimble.com/) informed the restrained palette, editorial
typography, generous spacing, and product-first presentation. PatchPilot uses its
own copy, code-native illustration, branding, and task layout. No reference
artwork, customer claims, or performance figures are copied.

The landing page (`/`) explains the focused PHP prototype and gives one primary
next step: **Open dashboard**. Its product illustration is explicitly an example.
The secondary walkthrough is explicitly simulated. The scope FAQ explains which
targets can be assessed and what approval authorizes.

The dashboard (`/dashboard`) supports observation and decisions. The order is
readiness → current site summary → URL assessment → registered sites → activity.
Primary navigation contains Overview and Activity log; mock-only insights and
recipe views stay out of the live workspace. Existing run and mock deep links
remain supported.

## HCI decisions

The implementation applies [Nielsen's usability heuristics](https://www.nngroup.com/articles/ten-usability-heuristics/)
through concrete interaction rules:

| Principle | Implemented behavior |
| --- | --- |
| Visible system status | Readiness explains missing prerequisites; progress uses recorded states; loading, failures, and final evidence are distinct. |
| User control | Assessment and repair are separate actions. Approval names the exact scope, starts with Cancel focused, and has a clear exit. |
| Error prevention | Unknown URLs are rejected locally, the entered value is retained, and repair remains gated by actual assessment and owner approval. |
| Recognition | Registered URLs can fill the form; site filters and readable check labels reduce recall. |
| Consistency | Shared color, spacing, control, icon, and status tokens serve both screens. Ordinary navigation links expose their current location. |
| Minimalism | One URL assessment action leads the page; raw identity/configuration evidence is disclosed on request. Earlier failures remain visible. |

Keyboard focus follows the [W3C focus-visible guidance](https://www.w3.org/WAI/WCAG22/Understanding/focus-visible.html).
Dialog backgrounds become inert, focus stays in the review, and cancel returns to
the invoking control. Polling preserves drafts, cursor selection, disclosure
state, and focus. A dedicated live region announces operation changes without
re-announcing the entire page. Statuses include text and symbols alongside color.

## Components and verification

`design.css` owns shared foundations. `styles.css` owns the workspace;
`landing.css` owns the public page. Small modules provide SVG icons, readiness,
site records, approval, progress, and evidence. All assets remain local, with no
frontend framework or build dependency.

`scripts/verify-ui.cjs` checks landing/deep-link routes, keyboard and modal behavior,
URL boundaries, 320/768/1024/1440px layouts, simulated success/restoration, and
polling persistence. When axe-core is installed, it also checks WCAG A/AA rules.
The harness blocks external requests and HTTP mutations. Browser checks supplement
the API and Python tests; automated checks alone do not establish complete
accessibility conformance or replace usability testing with participants.

## Screens

[Landing page](screens/landing.png) · [Live dashboard](screens/dashboard.png) ·
[Mobile dashboard](screens/dashboard-mobile.png) ·
[Actual assessment review](screens/assessment.png) ·
[Historical repair evidence](screens/report.png)

The assessment screenshot shows a real local PHP 8.3.35 observation. The report
shows a previously completed run and carries its historical-result notice; the
current fixture baseline remains unpatched until a new repair is approved.

## Recorded validation

On 2026-10-24, the interface passed 18 browser checks at 320/768/1024/1440px,
including keyboard review/cancel, simulated success/restoration, readable mobile
tables, and draft/disclosure/checkbox/scroll persistence through polling. Axe
reported no WCAG 2/2.1 A/AA violations in the tested screens; browser console and
page errors were empty. The guarded harness made no external requests or HTTP
writes. Its screenshots remain in the ignored `var/ui-qa-final/` directory.

Separately, a real UI session prepared the local fleet, selected a registered URL,
reviewed actual PHP 8.3.35 assessment evidence, and canceled before repair. The
deterministic Python suite passed 148 tests; API contract checks, five mock
scenarios, all 20 JavaScript syntax checks, and the package build also passed.
