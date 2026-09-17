---
id: OME-911
linear_url: https://linear.app/openmined/issue/OME-911/dependabot-backlog-sweep-close-the-obsolete-url4-cloud-pr-and-land-the
status: In Progress
type: Task
priority: High
labels: [repo, agentic, autonomous, task]
created: 2026-08-20
closed:
---

# Dependabot backlog sweep after the ScreamingFace org transfer

Eleven open Dependabot PRs. Close what is structurally dead, land what is green, and hand the
genuinely-blocked ones to their own work items rather than force-merging or closing them.
Repeat of `OME-734` under epic `OME-733`.

`#641` was closed as obsolete rather than rebased: `apps/url4-cloud` no longer exists on main
(renamed to `apps/screamingface-engine` by `9b888579`), and `#645` is its green successor.

`#640` and `#637` were left for `OME-912` / `OME-913` — both were red for one shared reason,
a tortoise-orm 1.1.8 typing regression, not a flake.

Canonical artifacts:

- Ledger: `docs/work/2026-08-20-OME-911-dependabot-backlog-sweep.md`
