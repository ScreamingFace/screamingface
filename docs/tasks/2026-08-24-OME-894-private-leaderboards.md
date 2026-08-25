---
id: OME-894
linear_url: https://linear.app/openmined/issue/OME-894/support-private-leaderboards-starting-with-healthbench-worst-30
status: in_review
type: task
priority: P1
labels: [scoreboard, agentic, autonomous]
created: 2026-08-24
closed:
---

HealthBench worst-30 is the public entry challenge, so its submissions must not be publicly
visible: staff see everyone's, participants see only their own. Implemented as a general
`Benchmark.visibility` capability rather than a special case.

Privacy is enforced in the API across all four read paths, not in the portal — the portal is
static JavaScript against a public API, so hiding rows in the page would leave
`curl /v1/leaderboard/healthbench-worst30` serving everything.

Spec: `docs/spec/2026-08-24-OME-894-private-leaderboards.md`
Plan: `docs/plan/2026-08-24-OME-894-private-leaderboards.md`
Ledger: `docs/work/2026-08-24-OME-894-private-leaderboards.md`
