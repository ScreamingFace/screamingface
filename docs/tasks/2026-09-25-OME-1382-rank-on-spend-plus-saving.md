---
id: OME-1382
linear_url: https://linear.app/openmined/issue/OME-1382/rank-the-pareto-frontier-on-spend-plus-cache-saving
status: backlog
type: task
priority: high
labels: [scoreboard, agentic, deferred]
parent: OME-1251
created: 2026-09-25
closed:
---

# Rank the Pareto frontier on spend plus cache saving

Phase 2 of D5 on epic `OME-1251`, split out of `OME-1325` at its close. The board stores
`cache_saved_cost_usd` (#1055) and the client sends it (#1075); nothing reads it yet.

**Blocked by `OME-1287`** (E2). Until every call is priced, the saved figure understates the true
cost. Blocks `OME-1143`.

Open before implementing: whether the read API serves the sum as `run_cost_usd` (A) or serves
the saving and lets the portal sum (B). Leaning A. The chart must plot the number the frontier
ranks on.

- 2026-09-25: filed from `OME-1325` phase 2.
