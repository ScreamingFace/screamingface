---
id: OME-1382
linear_url: https://linear.app/openmined/issue/OME-1382/rank-the-pareto-frontier-on-spend-plus-cache-saving
status: done
type: task
priority: high
labels: [scoreboard, agentic, deferred]
parent: OME-1251
created: 2026-09-25
closed: 2026-10-05
---

# Rank the Pareto frontier on spend plus cache saving

Phase 2 of D5 on epic `OME-1251`, split out of `OME-1325` at its close. The board stores
`cache_saved_cost_usd` (#1055) and the client sends it (#1075); nothing reads it yet.

No longer blocked by `OME-1287` (owner, 2026-10-02). Approach A: the read paths serve
`run_cost_usd` as spend plus saving for a `complete` row with a saving; the private export keeps
the stored fields. Ships in two halves: this board half first, then a `client-sf` leaf under
`OME-1251` that sends a cached run as `complete` only when every hit carries a price,
reported or archive (D7). Blocks
`OME-1143`.

Spec: `docs/spec/2026-10-02-OME-1382-rank-on-reproduction-cost.md`.
Ledger: `docs/work/2026-10-02-OME-1382-rank-on-reproduction-cost.md`.

- 2026-09-25: filed from `OME-1325` phase 2.
- 2026-10-02: unblocked; board half built (`reproduction_cost`, five read paths).
- 2026-10-02: extended for `OME-1251` D7: the archive-matched saving is stored (migration `0017`) and summed.
- 2026-10-05: merged via #1227 (`8c4db51e`), approved after PostgreSQL verification; closed in Linear with the close comment. SQLite unreadable-saving follow-up to be filed under `OME-1251`.
