---
id: OME-1776
linear_url: https://linear.app/openmined/issue/OME-1776/release-notes-cover-every-commit-since-each-packages-last-release
status: in_review
type: task
priority: urgent
labels: [repo-dev-processes, agentic, autonomous]
parent: OME-1138
created: 2026-10-29
---

# Release notes cover every commit since each package's last release

release-please read at most 500 commits per run, so the open release PRs #512 (aigateway 1.0.0),
#1386 (screamingface-engine 1.6.0) and #1385 (url4 1.6.0) missed everything before 2026-10-13,
including the breaking change #1082. `release-please-config.json` now sets `commit-search-depth`
to 5000, kept permanently. The AIGateway manifest points at the published `0.2.0` tag rather than
the untagged `0.2.1` draft, so its walk has a real release boundary. The PR also lands the OME-1138
close-out spec and plan.

- 2026-10-29: filed, implemented, PR opened. After merge: confirm the regenerated release PRs and
  edit the aigateway 1.0.0 notes so the removed purge command is not listed under Features.
