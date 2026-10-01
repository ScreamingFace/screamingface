---
id: OME-1443
linear_url: https://linear.app/openmined/issue/OME-1443/pushing-a-docs-only-branch-runs-every-stacks-test-suite-when-the
status: done
type: fix
priority: medium
labels: [repo-dev-processes, agentic, autonomous]
parent: OME-1321
created: 2026-10-01
closed: 2026-10-01
---

# Pushing a docs-only branch runs every stack's test suite when the remote is named `upstream`

The pre-push hook gates each stack a branch changed, found by diffing against a base. With no
`origin/main` (remote named `upstream`) it fell back to the local `main`, which lagged the
remote by 8 commits touching three stacks, so a docs-only push ran the engine, aigateway and
aigateway-ui checks. The hook now uses `upstream/main`, then `origin/main`, and stops with a
fix-it message when neither exists; it never uses a local branch.

- 2026-10-01: filed with its PR (branch `OME-1443-pre-push-base-fallback`, ledger
  `docs/work/2026-10-01-pre-push-base-fallback.md`). The branch's own push took 4 s with the
  fixed hook.
