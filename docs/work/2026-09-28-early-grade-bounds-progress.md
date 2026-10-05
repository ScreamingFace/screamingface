---
ticket: OME-932
stack: screamingface-engine
status: done
started: 2026-09-28
finished: 2026-09-28
---
# Early grade bounds and failure progress

## Intent
Reject oversized direct early-grade requests before asset loading, and publish canonical terminal failures resolved by final aggregation.

## Planned changes
Require available count in shared endpoint and every board wiring. Publish synthesized failures through the existing deduplicated progress port; prevent fast terminal failures being suppressed by score coalescing.

## Test plan
Real URL4 endpoint with spy loader: oversized count never loads. Mixed scored/collected-failure and all-failure runs: completed counts advance once, gradeable score is unchanged or absent, repeat aggregation deduplicates. Full Engine gates.

## Acceptance
No unbounded selection allocation from direct calls; failed cases advance completion without inventing grades.

## Outcome
- Shared endpoint requires board availability and checks count/position before cache or loader access. All built-in wiring passes its existing aggregate limit.
- Aggregation publishes only newly constructed canonical failures; existing run observer deduplicates repeats. Unscored terminal failures bypass fast-score coalescing.
- Eight new regressions cover oversized/invalid counts, accepted upper boundary, mixed and all-failed progress, repeated aggregation and unchanged/absent score. Existing generated-route timing tests remain green.
- Full Engine gates pass: lint, format, types, layering, tests and coverage. No prior tests changed; branch-wide fixture migrations retain the previously approved append-only exception.
- Wisdom: limits use the same board authority as aggregation, no allocation precedes validation; progress remains optional and final scoring unchanged. No new protocol revision or paid calls.
- Commit: `fix: bound early grading and report terminal failures`.
- Deviations: none.
