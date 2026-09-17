---
ticket: OME-567
stack: url4-cloud
status: done
started: 2026-07-22
finished: 2026-07-22
---

# OME-567 — url4-cloud release-please lane (image; Helm publish deferred)

## Intent

Register `apps/url4-cloud` with release-please (mirroring `apps/aigateway`) + a release workflow
that builds/pushes the GHCR image on tag `url4-cloud-v*`. Lands in the existing PR #419.

## Planned changes

- `release-please-config.json` — add `apps/url4-cloud` (`release-type: python`, `component:
  url4-cloud`, `tag-separator: -`, `include-component-in-tag: true`, `version-file:
  apps/url4-cloud/pyproject.toml`).
- `.release-please-manifest.json` — add `"apps/url4-cloud": "0.1.0"`.
- `.github/workflows/release-url4-cloud.yml` — on tag `url4-cloud-v*` (+ workflow_dispatch): verify
  version vs pyproject; build/push `ghcr.io/openmined/screamingface-url4-cloud` (context
  `apps/url4-cloud`, multi-arch); `helm lint` the chart; draft GitHub Release.

## Test plan

- JSON parses; `apps/url4-cloud` in config + manifest.
- `release-url4-cloud.yml` is valid YAML.
- `helm lint apps/url4-cloud/deploy/helm` passes (warning-only on the missing NATS dep — verified).
- No app/python code changes → `run_gates` categories (ruff/pyright/pytest) N/A; confirm the app
  test suite still green (unchanged).

## Acceptance

url4-cloud registered in release-please (valid JSON) + `release-url4-cloud.yml` valid YAML mirroring
aigateway (image + chart-lint + draft release, chart-publish deferred); committed to PR #419.

## Deviations / follow-up

- **Helm OCI chart publish deferred.** The chart (`apps/url4-cloud/deploy/helm`) declares a NATS
  dependency at a placeholder version (Chart.yaml NOTE: "confirm before enabling"), so
  `helm template`/`helm package` fail (`missing in charts/`). The workflow lints the chart but does
  not `dependency build`/`package`/`push` until NATS is pinned + vendored — a follow-up.

## Outcome

- **Actual files:** `release-please-config.json` (added the `apps/url4-cloud` package, mirroring
  aigateway) · `.release-please-manifest.json` (added `"apps/url4-cloud": "0.1.0"`) ·
  `.github/workflows/release-url4-cloud.yml` (new — verify · image (GHCR
  `screamingface-url4-cloud`, context `apps/url4-cloud`, multi-arch) · chart `helm lint` · draft
  GitHub Release).
- **Commits:** see the OME-567 commit on `OME-513-url4-cloud` (pushed to PR #419).
- **Gates:** JSON valid, `apps/url4-cloud` in config + manifest; workflow **YAML valid**; `helm lint
  apps/url4-cloud/deploy/helm` passes (0 failed; NATS-missing warning is expected); manifest `0.1.0`
  matches `apps/url4-cloud/pyproject.toml`. No app/python code changed.
- **Deviations:** **Helm OCI chart publish deferred** — the chart's NATS dependency is a placeholder
  (Chart.yaml NOTE), so `helm template`/`package` fail; the workflow lints the chart only until NATS
  is pinned + vendored. The aigateway lane's **sf-installer** public-release step was **omitted**
  (url4-cloud isn't production-ready — merge gates open); GHCR image + draft GitHub Release only.

## Closure justification (OME-1215, round 2)

This ledger's `status:` was `in_progress` with the unit's work already merged, while the
`docs/tasks/` mirror said `done` — the mirror was the correct side. `OME-1215` closed the
ledger, which is an edit to an audit record, so the owner required the closure to be
justified with evidence rather than asserted.

EVIDENCE, verifiable from this repo: the unit's work is on `origin/main` as `2f628696`
(`ci(url4-cloud): register release-please lane + release workflow`), authored 2026-07-22. `finished: 2026-07-22` is that commit's author date — read
from git, not reconstructed.

WHAT IS *NOT* CLAIMED: nothing about why the ledger was left open, and nothing about the
ticket's Linear state. Only that the work in this ledger reached `main` on the date given.
