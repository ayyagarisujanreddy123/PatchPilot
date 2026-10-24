# Repository Guidelines

## Project Structure & Module Organization

PatchPilot currently contains specifications only:

- `PatchPilot_Product_Overview.md`: mission and workflow summary.
- `PatchPilot_Product_Statement.md`: audiences and intended experience.
- `PatchPilot_Technical_Statement.md`: architecture, verification contract, and acceptance gates.

The planned prototype combines a FastAPI API/dashboard, a sequential repair worker, four local Apache/PHP Docker fixtures, JSON recipes, and an append-only event log. No source, test, or asset directories exist yet. When scaffolding, prefer `src/patchpilot/`, `tests/`, `fixtures/`, and `src/patchpilot/static/`; document the adopted layout.

## Build, Test, and Development Commands

No application commands or dependency manifests exist yet.

- `rg --files -g '*.md'`: list project documentation.
- `git diff --check`: check tracked changes for whitespace errors.

Add reproducible installation, server, fixture, test, and lint commands with the first implementation. Label proposed commands clearly until they work.

## Coding Style & Naming Conventions

Use four-space indentation in Python/PHP, Python type hints, `snake_case` for Python modules/functions, and `PascalCase` for classes. Keep assessment, planning, control, verification, and recipe storage separate. No formatter or linter is configured; document tool choices when introduced. Distinguish proposed capabilities from measured results in documentation.

## Testing Guidelines

No testing framework or coverage threshold exists. Prefer pytest for Python, with `tests/test_*.py` files and `test_*` functions. Cover the HTTP-serving runtime, homepage/contact validation, a real 3 MiB upload with byte-count/hash checks, recipe reuse, staging rejection, and verified restoration after activation failure. Repeat checks after activation. Never weaken assertions to pass a repair.

## Commit & Pull Request Guidelines

No Git history exists, so there is no established message convention. Use focused commits such as `docs: clarify repair approval` or `feat: add candidate verifier`. PRs should explain behavior, link relevant issues or specification sections, report validation results, and include screenshots for dashboard changes. Update affected specifications.

## Security & Configuration

Operate only on authorized, registered local targets. Keep credentials outside model inputs and Git. Allow only approved images/configuration profiles; bound attempts and readiness waits. Reset only project resources and retain completed run records. Verify advisory and image versions against authoritative sources before implementation. Report restored vulnerable deployments as unpatched.
