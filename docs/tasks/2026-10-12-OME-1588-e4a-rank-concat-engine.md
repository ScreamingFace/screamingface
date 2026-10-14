---
id: OME-1588
linear_url: https://linear.app/openmined/issue/OME-1588/add-rank-concat-filter-and-pick-by-signal-operators
status: in_progress
type: feature
priority: 3
labels: [screamingface-engine, agentic, autonomous]
created: 2026-10-12
closed:
---

# Add rank, concat, filter and pick-by-signal operators

Mirror of OME-1588 (parent epic OME-1289). PR 11 of 16 in the E4a stack, branch
`OME-1588-e4a-rank-concat-engine` on `OME-1587-e4a-pick-merge-engine`.

`top_k@1` (with `order: min` and `cut_not_met`), `join@1`, `all@1`, `by_signal@1`, `best_holder@1`, `filter@1` and `kept@1`: keep k members, join their texts, drop members by a signal threshold or a regex, or pick the member with the best signal such as the lowest cost.

Ledgers: `docs/work/2026-10-01-e4a-rank-concat-engine.md`, `docs/work/2026-10-02-e4a-gap-closure-unit10e.md`.
