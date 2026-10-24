# PatchPilot Product Statement

*Self-Healing Security for Small Businesses*

Product concept  |  24 October 2026

**PatchPilot is an autonomous security agent designed to help small businesses, nonprofits, and community organizations turn an urgent security notice into a verified website repair.** After an authorized connection and owner approval, it identifies supported vulnerabilities, prepares the fix, checks that essential website functions still work, and records the outcome.

## Our mission

Every food pantry, family restaurant, and local clinic deserves access to practical security maintenance. Our goal is to make that protection available at no cost to the organizations that need it, with minimal technical effort after setup. Owners should be able to understand the issue, approve a repair, and see evidence that it worked.

## The problem we address

An urgent advisory leaves an owner with several unanswered questions: Does this affect my website? Who can apply the update? Could it break a contact form, appointment request, donation page, or document upload? A published fix does not complete those tasks.

PHP released emergency fixes for two critical vulnerabilities on October 21, 2026. That incident provides PatchPilot's initial use case: helping an organization move from a software warning to a checked update. [1]

PatchPilot is intended for organizations without dedicated technical support and for the trusted people who maintain websites on their behalf. The product reduces the work of assessing, applying, verifying, and documenting supported repairs.

## Who it serves

| **Audience** | **What they need** |
| --- | --- |
| Small-business owner | A plain-language result and a repair they can approve. |
| Nonprofit or community organization | A dependable website without a dedicated security team. |
| Volunteer or community IT helper | One authorized workflow across several organizations. |

**Product promise:** a clear path from an identified issue to a tested repair, with an understandable outcome when automation needs help.

## The intended product experience

1. **Connect with permission.** Connect a supported website or hosting environment that the owner controls.

2. **Understand and approve.** Review a plain-language finding, the proposed changes, and the functions that must keep working. One approval starts the repair.

3. **Prepare and verify.** Apply the candidate update to an isolated copy and check both the security condition and required application behavior.

4. **Activate or recover.** Activate a passing candidate and check it again. Reject a failing staging candidate; if activation fails, attempt a verified restoration of the previous deployment.

5. **Receive clear evidence.** See what changed, what passed, what remains unresolved, and when human help is needed.

## Experience that improves the next repair

PatchPilot stores successful repair plans together with their requirements, failed checks, and verification results. When a later site has a matching configuration, it can reuse that knowledge and avoid repeating the same planning work. Every site still receives its own checks. Improvement is measured through recipe reuse, planning effort, attempts, and actual outcomes.

## Initial prototype and product direction

The planned hackathon demonstration uses four local PHP sites. It will show a real runtime update, detection of a deliberately introduced compatibility problem, a corrected plan, and transfer of the verified repair to a matching site. These are acceptance goals for the build.

The wider product direction includes supported hosting connections, continued advisory monitoring, more application environments, and assistance when automation reaches its limits. No-cost access remains the mission; sustainable infrastructure and support must be established as the service develops.

## What success means

An owner can approve a supported repair, see that essential website behavior was checked, and receive a clear record of the result. A volunteer can repeat that process across authorized sites while reusing verified knowledge. The initial prototype will evaluate this workflow before broader deployment.

### Source

[1] [PHP security announcements](https://www.php.net/index.php)

Product capabilities above describe the intended experience and prototype goals.
