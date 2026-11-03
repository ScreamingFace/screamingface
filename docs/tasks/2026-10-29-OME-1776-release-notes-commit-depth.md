---
id: OME-1776
linear_url: https://linear.app/openmined/issue/OME-1776/release-notes-cover-every-commit-since-each-packages-last-release
status: done
type: task
priority: urgent
labels: [repo-dev-processes, agentic, autonomous]
parent: OME-1138
created: 2026-10-29
closed: 2026-11-02
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
- 2026-10-30: squash-merged to `main` as `f76cacf85` (PR #1607).
- 2026-11-02: the regenerated release PRs carry the missing entries: #512 starts from
  `aigateway-v0.2.0` and lists #1061 and #1114; the screamingface-engine 2.0.0 notes (#1386) list
  #1082 and #1231; #1385 lists #1231. The aigateway 1.0.0 notes are corrected through commit
  overrides on #1573 (the purge, removed at E5c, leaves Features), #1491 and #1614 (the final
  breaking entries). Linear closed the issue Done the same day with the close comment.
