# Live website assessment

## Objective

Accept a public website URL, inspect fresh HTTP responses, assess observable PHP
and web-server security signals, and obtain Anthropic recommendations tied to
recorded evidence. This becomes the dashboard's default task. The four local
fixture repairs remain a separately labeled repair lab.

## Interface and modules

- `webscan/network.py`: bounded normal HTTP GETs with DNS/IP pinning, TLS checks,
  response limits, and validation of every redirect. Public HTTP(S), ports 80/443.
- `webscan/models.py`, `rules.py`: typed reports, evidence, PHP confidence, observed
  configuration findings, references, and explicit coverage/unknowns.
- `webscan/agent.py`: fresh collection of the submitted URL and bounded redirects,
  then streamed, structured Anthropic fix suggestions. No prior-result templates or fixture
  observations are substituted when collection/provider access fails.
- `backend/website_api.py`: session/CSRF-protected job creation, progress/report
  polling, exclusive admission, bounded shutdown, safe persistence.
- Static website-assessment view: real URL form, live stages, timestamped evidence,
  PHP detection confidence, findings, suggested configuration/code, and rescan.

`POST /api/website-assessments {url}` returns 202 `{assessmentId,statusUrl}`.
`GET /api/website-assessments/{assessmentId}` returns the report below; GET the
collection for this session's reports. Queued/collecting/analyzing/completed/failed
states are independent from verified deployment-repair states.

## Boundaries and success

Use ordinary GET requests only. No exploit payloads, hidden-file discovery,
credential use, form submissions, broad crawling, server changes, or automatic
PRs. Reject private/reserved destinations and DNS/redirect rebinding. Never log
or send cookie values, authorization data, query tokens, full HTML, or raw error
pages to the model. Model text is rendered as text and never executed.

Header banners and `.php` links are evidence of varying confidence, not proof of
an installed PHP build. Missing hardening headers are configuration observations,
not confirmed XSS/SQL injection. Source-level vulnerabilities and installed PHP
patch/backport status require authorized source/server access. Reports state this
coverage plainly; a successful assessment is not a declaration of a safe website.

## Validation and demo

Pytest tests cover SSRF and redirect handling, bounded transport, changed responses,
PHP unknown/reported/inferred cases, evidence-linked findings/recommendations,
provider failures, session isolation, and real job progress. Browser checks cover
URL entry and the actual report. The MVP's live normal-GET demonstration uses
Invicti's documented PHP testing site, `http://php.testsparker.com/`, recording
timestamps and response hashes; no exploitation is performed or claimed.
Actual Anthropic text chunks drive progress messages; accepted output records
the provider message ID, model ID, and input/output token counts. Partial or
invalid responses retain HTTP evidence and fail without substitute recommendations.

Commands: `uv run --locked --extra dev python -m pytest tests/webscan tests/backend`;
`uv build`; frontend syntax/API checks; real-browser exercise from `/dashboard`.
Use Python four-space indentation, typed models, and camelCase JSON at the API.
