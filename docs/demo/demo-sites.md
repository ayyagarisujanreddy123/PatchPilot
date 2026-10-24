# Choose a demo website

Open [the local dashboard](http://127.0.0.1:8765/dashboard). Choosing a sample
fills the URL field; **Assess website** starts fresh collection and analysis.
Results depend on the responses received during that run. A sample listing does
not promise a particular PHP version, finding, or safety outcome.

| Demo | Website URL | Supported flow |
| --- | --- | --- |
| Connected PHP community demo | [Owned community site](https://believe-joke-magnificent-techniques.trycloudflare.com/) | Public assessment, then a tested repository configuration change and an explicitly reviewed draft PR. |
| Invicti PHP test site | [http://php.testsparker.com/](http://php.testsparker.com/) | Public assessment only. |
| PHP official website | [https://www.php.net/](https://www.php.net/) | Public assessment only. |
| phpIPAM public demo | [https://demo.phpipam.net/](https://demo.phpipam.net/) | Public assessment only. |

The owned site's current URL is a temporary Cloudflare tunnel. If it expires,
use the current **Connected PHP community demo** entry in the dashboard, or
restart it using the [connected demo setup](connected-repair.md). The catalog
contains URL metadata, not saved assessment results.

## Try the complete repository repair flow

1. Assess the **owned community site URL** above and wait for completion.
2. Expand **Connect your GitHub repository** and use
   [ayyagarisujanreddy123/patchpilot-connected-demo](https://github.com/ayyagarisujanreddy123/patchpilot-connected-demo).
   A pasted URL ending in `/tree/main` is accepted and normalized to the
   repository home URL. It still refers to the same repository.
3. Use a locally signed-in GitHub account with write permission. Select the
   homepage, contact, and upload checks, then connect and **Prepare tested fix**.
4. Review the original and candidate checks, the exact PHP configuration diff,
   and the real upload size/hash evidence. Only a passing candidate enables
   **Create draft pull request**. That action creates a PR; it does not merge,
   deploy, or change the live website.

## Why a website and repository may not connect

The assessed website must identify the repository it actually represents through
a same-origin `/.well-known/patchpilot.json` deployment marker. Its `repository`,
current default-branch `commit`, and `siteId` must match the chosen repository and
its supported `.patchpilot.json` profile. This is declared deployment identity,
not independent build attestation.

Assessing **Invicti** and then pasting the owned community repository will not
connect: those are different websites. Accepting a `/tree/main` URL fixes the
repository URL format; it does not bypass deployment identity or write access.

Invicti, PHP.net, and phpIPAM are examples for bounded normal public HTTP
assessment. This flow does not log in, submit forms, run exploit tests, or change
those websites. Their sample entries provide no repository repair permission;
suggested changes remain recommendations. To test another repository repair,
use a website and repository you control with a matching deployment marker and
supported profile.
