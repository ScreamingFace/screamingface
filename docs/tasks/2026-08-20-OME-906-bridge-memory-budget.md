---
id: OME-906
linear_url: https://linear.app/openmined/issue/OME-906/cached-draco-evaluations-overflow-the-runner-event-bridge
status: in_progress
type: bug
priority: 1
labels: [screamingface-engine, agentic, autonomous]
created: 2026-08-20
closed:
---

# Cached DRACO evaluations overflow the runner event bridge

The ticket blamed a slow consumer; measurement disproved it. The 8 192-event count cap
bounded DAG WIDTH, not backlog health: the engine fans out over `deps` with an unbounded
gather and emits each node's `NodeStarted` before it awaits anything, so a wide fan-in
lands its whole event burst in one event-loop slice, before the drain can run at all. A
100-Case DRACO Fusion is legitimately ~3 500 nodes wide and sat at the limit. The cap
defended 2.1 MB in a process that accepts a 1 GiB result.

Fix: bound the bridge by a MEMORY BUDGET (default 64 MiB ≈ 131 072 events at a 512 B
estimate), readable from `URL4_CLOUD_BRIDGE_MEMORY_BUDGET_BYTES` like the result caps,
and make the overflow error say which failure shape fired — drain progress above zero is
one DAG burst wider than the budget; zero drained events is a stuck consumer.

Investigation byproducts shipped separately in PR #667 (pipelined JetStream publishing,
~50x wall-clock at a 10 ms round trip, and the bridge high-water mark this fix builds
on): `docs/spec/2026-08-20-OME-906-pipelined-frame-publishing.md` records that history.

Spec `docs/spec/2026-08-20-OME-906-bridge-memory-budget.md`, plan
`docs/plan/2026-08-20-OME-906-bridge-memory-budget.md`, ledger
`docs/work/2026-08-20-OME-906-bridge-memory-budget.md`. Stacked on PR #667; retarget to
`main` after it merges.
