# Victor: website to tested GitHub repair

Open `http://127.0.0.1:8765/dashboard`, select **Try the PHP demo**, and start the
website assessment. Victor collects real HTTP evidence and streams analysis.
The connected local demo supplies its current public URL as sample metadata;
no result is preloaded.

After assessment, expand **Connect your GitHub repository**. For the owned demo,
use `https://github.com/ayyagarisujanreddy123/patchpilot-connected-demo`. Choose
homepage/contact/upload checks and connect. Select **Prepare tested fix**. Review
the baseline, candidate, exact INI diff, and actual provider provenance. Select
**Create draft pull request** only after review. The live website is not changed.

## Reproduce the serving demo

With Docker and `gh auth login` configured, run:

```bash
DOCKER_CONTEXT=lima-patchpilot-demo uv run python scripts/setup-connected-demo.py \
  --repository YOURLOGIN/patchpilot-connected-demo --port 8085
cloudflared tunnel --url http://127.0.0.1:8085 --no-autoupdate --protocol http2
```

Assess the resulting public HTTPS URL. Its marker binds the dedicated repository,
deployed commit, and site ID. A quick-tunnel URL lasts only while its process runs.
For a local sample shortcut, write `var/connected-demo/public.json` with `url` and
`repositoryUrl`. This ignored file contains metadata only. Other supported repos
need the manifest and deployment marker documented in the specification.

## Actual acceptance on 2026-10-24

The real browser run assessed the public community demo and created
[draft repair PR #1](https://github.com/ayyagarisujanreddy123/patchpilot-connected-demo/pull/1).
Repair `repair-7282087d84ec4bb7b436e118714245b5` ran from 19:52:28 to 19:52:49 UTC.
The deployed/base commit was `13d2ed441cde3ee39eb0fdc128ee68e1d4ecbeae`.

Baseline: **6/11 passed**, with five security findings and all selected business
checks passing. Candidate: **11/11 passed**, including contact valid/invalid
responses and a real 3 MiB upload with matching size/hash. The exact one-file diff
disabled error/startup display and PHP exposure, enabled logging, and preserved
upload/post limits. Actual Anthropic model `claude-sonnet-5-5` used 1,288 input and
198 output tokens. There were no browser errors. No production deployment or
complete security audit is claimed.
