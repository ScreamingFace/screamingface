# OME-931 — Sequential outer benchmark Case evaluation

- **Linear:** https://linear.app/openmined/issue/OME-931/evaluate-benchmark-cases-sequentially
- **Landing:** `apps/screamingface-engine`
- **Related discovery:** `OME-887` provisional-score latency

## Problem

The shared benchmark protocol currently leaves its outer Case iteration at URL4's default map
concurrency. A multi-Case evaluation can therefore spread work across many Cases before any one
Case has completed candidate invocation, grading, and Case-result construction. That delays the
first complete Case outcome and multiplies Case-level resource pressure.

## Required behavior

The outer Case iteration MUST set `iteration.concurrency=1`. The semaphore covers the complete
spawned row expression, so the next Case begins only after the current Case returns or raises.

This bound is intentionally scoped:

- Nested iterations and fan-out inside the active Case retain their existing concurrency.
- Separate benchmark runs retain independent schedulers and can execute concurrently.
- Fetching the Case collection, resolving shared bindings, and final aggregation remain outside
  the Case semaphore.
- Per-Case `on_error=collect`, selection slicing, and ordered result collection remain unchanged.

## Design

Add `concurrency=1` to the one shared `iterate(...)` call in
`screamingface_engine.benchmarks.protocol.build_evaluation_protocol`. Do not change URL4: its
`MapNode` already holds the per-map semaphore across the entire spawned row subtree.

Keep `EVALUATION_PROTOCOL_REVISION` unchanged. Benchmark revision identifies the dataset and
scoring contract — the thing measured — while Case admission is an operational scheduling
choice. The rendered URL4 recipe changes and its byte pins must move, but existing scores remain
comparable and the Scoreboard's registered benchmark revisions must not move.

## Acceptance criteria

1. A deterministic shared-protocol test observes a maximum of one active Case endpoint.
2. The generated outer iteration renders `iteration.concurrency=1`.
3. Failure collection, selected order, and aggregation output remain unchanged.
4. IFEval, DRACO, and both HealthBench boards retain their existing benchmark revisions.
5. Canonical rendered URL4 SHA-256 pins move to the sequential recipes.
6. No URL4 package or Scoreboard code changes.
7. The full `screamingface-engine` gate passes.
