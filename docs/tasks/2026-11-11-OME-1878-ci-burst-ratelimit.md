---
id: OME-1878
linear_url: https://linear.app/openmined/issue/OME-1878
status: done
type: task
priority: 3
labels: [repo-dev-processes, agentic, autonomous]
parent: OME-733
created: 2026-11-11
closed: 2026-11-16
---

# Stop a burst of merges failing runs on the GITHUB_TOKEN rate limit

Release Please concurrency, non-failing report steps, and a reconcile that skips on a spent token limit. Ledger: `docs/work/2026-11-11-ci-burst-ratelimit.md`.

Scope: Release Please, the Preview reconcile and the test lanes' report steps. CodeQL is not covered — residual `OME-1927`.
