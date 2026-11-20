---
ticket: OME-1983
stack: repo
status: done
started: 2026-11-20
finished: 2026-11-20
---

# pin-helm-in-ci — every CI job installs the same Helm

## Intent

Eight `azure/setup-helm@v5.0.1` steps set no `version:`, so each job looks up the latest Helm
release. When that lookup failed on #1896 (2026-11-20), the action fell back to Helm v3.18.4 and a
chart test that expects Helm 4's schema error wording went red, unrelated to the diff. Pin the
version our green runs use, so a red check means the code changed.

## Planned changes

- `.github/workflows/{charts,release-aigateway-ui,release-aigateway,release-report-intake,release-scoreboard,release-screamingface-engine,screamingface-engine-tests}.yml`: `with: version: v4.3.2` on each unpinned `setup-helm` step (eight). `analytics-tests.yml` keeps its own `v3.17.3`.

## Test plan

- Parse every workflow and list each `setup-helm` step's `with`: all nine carry a version.
- CI on this PR: the Engine chart tests and the release lint steps run on v4.3.2.

## Acceptance

- No `setup-helm` step without a `version:`.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, plus this ledger and the mirror.
- **Commits:** the pin and these docs.
- **Gates:** YAML parse of every workflow: nine `setup-helm` steps, each with a version. CI runs the rest.
- **Deviations:** none.
- **Owner verify:** a later Helm upgrade is now a reviewed edit of these eight lines.
