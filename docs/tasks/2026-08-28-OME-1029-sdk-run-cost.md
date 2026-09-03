---
id: OME-1029
linear_url: https://linear.app/openmined/issue/OME-1029/send-run-cost-usd-on-leaderboard-submissions-from-the-sdk
status: done
type: feature
priority: P1
labels: [py-screamingface, agentic, autonomous]
created: 2026-08-28
closed: 2026-08-31
---

The last missing link in the run-cost chain. Scoreboard accepts `run_cost_usd`, the Engine produces
a run total, and the SDK holds it on `CandidateResult.usage.cost_usd` — but `_submission()` does not
put it in the payload, so `run_cost_usd` is null on every row of every board.

Unblocks `OME-822` (make cost required) and part B of `OME-923` (Pareto frontier marks), which
cannot mark anything while no row carries a cost.

Spec: `docs/spec/2026-08-28-OME-1029-sdk-run-cost.md`
Plan: `docs/plan/2026-08-28-OME-1029-sdk-run-cost.md`
Ledger: `docs/work/2026-08-28-OME-1029-sdk-run-cost.md`
