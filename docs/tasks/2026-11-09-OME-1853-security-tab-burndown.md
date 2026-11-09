---
id: OME-1853
linear_url: https://linear.app/openmined/issue/OME-1853/burn-the-security-tab-back-down-to-real-alerts-2026-11-sweep-392
status: in_progress
type: task
priority: medium
labels: [repo-dev-processes, agentic, autonomous, task]
parent: OME-733
created: 2026-11-09
closed:
---

# Burn the Security tab back down to real alerts (2026-11 sweep: 392 Dependabot + 14 CodeQL)

On 2026-11-06 the Security tab showed 392 Dependabot and 14 CodeQL alerts. 131 point at
`apps/server` and `apps/url4-cloud`, deleted from `main`; 67 repeat Engine pins in the Studio
runtime lock; 7 green security PRs sat unmerged; 4 CodeQL alerts are in the legacy desktop
build output. After dedup the live tree has 13 high or critical packages to bump.

PR 1 (this branch): Dependabot #1566's four Engine bumps (pypdf, certifi, filelock, Pillow 13)
plus the re-seal of the three Benchmarks whose Cases they change, published ids held by owner
ruling. Ledger: `docs/work/2026-11-09-engine-security-bumps.md`.

Remaining: dismiss the ghost alerts, merge the other green security PRs, bump the remaining
live packages per app group, exclude `apps/desktop/out` from CodeQL, time the url4 regexes.
