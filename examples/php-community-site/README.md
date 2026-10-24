# Community Care PHP repair demonstration

A small, working PHP website with contact validation and a temporary upload
endpoint. No emails, personal records, or uploaded files are retained. The PHP
configuration intentionally exposes runtime information for a controlled repair.

The `.patchpilot.json` profile identifies the source root, INI file, and supported
behavior checks. A deployment must serve `/.well-known/patchpilot.json` containing
the actual repository full name, deployed commit SHA, and matching `siteId`.
Generate the marker at deployment time so it can name the resulting commit.

Use PatchPilot's connected-demo setup script to create an owned repository and
local serving copy. The main application then connects that repository, verifies
a baseline and candidate with no-network Docker sandboxes, and can create a draft
PR after explicit review. Source and upload limits remain unchanged.
