---
ticket: OME-932
stack: screamingface-engine + screamingface
status: done
started: 2026-09-29
finished: 2026-09-29
---
# Live-score review corrections

## Intent
Address grader-crash classification, terminal-row partial scores, final progress flushing, contract/isolation coverage and stale documentation from #1096 review. Investigate leaderboard revision continuity without changing ranking policy or approving a reset implicitly.

## Planned changes
Shared endpoint exception boundary, Client terminal score fallback/abort behavior, explicit end-of-grading snapshot flush, exact schema and cross-package conformance tests, nested/board isolation tests, doc cleanup. Inspect revision registration and submission semantics before proposing rollout.

## Test plan
Failing regressions for unexpected grader exceptions and cancellation; all Client terminal paths; fast grading flush including aggregate failure; exact emitted attributes, real Client decoder, nested scope suppression and interleaved boards. Full affected-stack gates and review.

## Acceptance
Unexpected grader errors fail the run without leaking exception text; terminal rows without authoritative results do not show bare partial scores; coalesced final snapshot is delivered before aggregation exits; contracts and isolation are tested. Leaderboard decision remains explicit.

## Outcome
Correctness regressions now pass: unexpected grader exceptions abort the real IFEval execution; cancellation propagates; terminal rows suppress running-score fallback, including decode/interrupt/timeout after transport success. Explicit end-of-grading flush covers fast batches and exceptional final aggregation. Exact snapshot keys/types and the actual Client parser agree; nested candidate scope and interleaved board/revision isolation are covered. Corrupt final grade transport is a sanitized contract error. Removed three unused aggregate factories and reconciled stale docs. Engine and Client full gates passed (lint, format, types, tests/coverage; Engine layering; Client notebooks/build/distribution). An additional early-transport flush/dedup test passed targeted pytest and type checking after the full Engine run; pre-push reruns the Engine suite. Client gates used the notebook extra installed in the isolated test environment. No paid calls.

Wisdom review: no new schema, grader, dependency, or ranking policy; observation remains guarded and optional. Flush reuses the existing scorer and emits only when the revision changed. Error text is sanitized; cancellation is not caught. New regressions assert execution/UI behavior, not implementation structure. Native scorer evidence is retained intentionally (IFEval and exam scorers inspect checks); a compact retained projection requires its own parity design.

Leaderboard finding: store.py filters ranked scores by the currently registered benchmark revision. Existing protocol-pin changes therefore hide older scores from default rankings. Proposed continuity requires a separate transport route while retaining semantic scoring identity, subject to parity verification and user confirmation. No reset or revision policy change made.
