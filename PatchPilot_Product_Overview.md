# PatchPilot Product Overview

## Self-Healing Security for Small Businesses

**Status:** Product concept  
**Date:** 24 October 2026

## Security updates, with proof your website still works.

PatchPilot is an autonomous security agent designed for small businesses, nonprofits, and community organizations. It turns a supported security warning into a repair that can be approved, tested, and explained.

## The problem

### A published fix still leaves work for the owner.

Does this issue affect my site? Who can apply the update? Will the contact form, appointment request, donation page, or file upload still work? PatchPilot brings those questions into one guided repair process.

### Understand the issue

A plain-language finding and a clear plan for a supported repair.

### Verify the change

A separate candidate is checked before it replaces the existing site.

### Keep the evidence

A record of changes, tests, outcomes, and any help still needed.

## Our mission

### Practical security for every community organization.

Our goal is no-cost access for food pantries, family restaurants, local clinics, and other small organizations, with minimal technical effort after authorized setup.

Initial use case: PHP emergency fixes released October 21, 2026. [1]

Designed for owners managing one site and trusted helpers managing an authorized fleet.

## How it works

### From a warning to a verified repair

After a supported connection is authorized, one approval starts the repair workflow.

1. **Connect and assess.** Inspect the connected environment and explain which supported issue applies.
2. **Review and approve.** Show the proposed changes and the website functions that must keep working.
3. **Stage and test.** Prepare an isolated candidate. Check the security condition and required behavior.
4. **Activate and verify.** Recheck the site after deployment. If activation fails, attempt verified restoration.
5. **Record and reuse.** Save the outcome. Reuse matching verified repairs, with fresh checks on every site.

## When a candidate fails

A failed staging candidate is rejected while the original site keeps serving. PatchPilot can revise the plan or request help. Restoration after a live deployment is a separate recovery step; each outcome is reported clearly.

## Planned hackathon demonstration

Four local sites. A real runtime update. An upload test that catches a deliberately incompatible candidate. A corrected repair, then reuse on a matching site. Actual tests and plan provenance provide the evidence.

## Product direction

Supported hosting connections, continued advisory monitoring, broader application coverage, and accessible assistance. Repair reuse is intended to reduce repeated work; measured results will establish its benefit.

## Sources

1. [PHP security announcements](https://www.php.net/index.php), October 21 and 23, 2026.
2. [Censys PHP2Shell exposure and methodology](https://php2shell.censys.com/). Censys reports millions of services on affected versions. These are version-based exposure estimates, not counts of organizations or confirmed compromises; backported fixes and scan delays can affect classification.
