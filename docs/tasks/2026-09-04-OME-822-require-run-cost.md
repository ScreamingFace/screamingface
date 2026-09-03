---
id: OME-822
linear_url: https://linear.app/openmined/issue/OME-822/require-run-cost-usd-on-direct-leaderboard-submissions
status: in_review
type: task
priority: 2
labels: [scoreboard, agentic, deferred]
created: 2026-08-13
closed:
---

# Require run cost on direct leaderboard submissions

Make `run_cost_usd` mandatory and non-null on the direct Scoreboard submission contract now that
the accounting, run-total, persistence, and SDK-publish chain is shipped. Keep storage and every
read DTO nullable for imported and historical rows; zero continues to mean a genuinely free run.

## Artifacts

- Spec: `docs/spec/2026-09-04-OME-822-require-run-cost.md`
- Plan: `docs/plan/2026-09-04-OME-822-require-run-cost.md`
- Ledger: `docs/work/2026-09-04-OME-822-require-run-cost.md`
