---
ticket: OME-932
stack: screamingface-engine
status: done
started: 2026-09-28
finished: 2026-09-28
---
# IFEval early-grade proof

## Intent
Prove that IFEval can produce its canonical grade before the next candidate finishes and reuse typed results in final aggregation. This is an isolated execution proof, not deployed endpoint wiring.

## Planned changes
Expose the existing IFEval ScoredPath construction for reuse. Add an async two-case execution proof using the real check and case-envelope endpoints, a gated candidate, the shared grading iterator and canonical finalizer.

## Test plan
Pause second candidate; assert the first grade is already available. Count deterministic check invocations and canonical grade calls. Compare the complete final payload with the existing batch aggregate. Cover successful and failed instruction checks.

## Acceptance
No copied grade logic; no duplicate checking or grading in incremental execution; final payload parity. No modification to existing tests, expressions, revisions or production routes.

## Outcome
Added a reusable IFEval scored_path factory and a test-only incremental execution using real checker/envelope node routes. Passing and failing instruction responses both yield the first canonical grade while candidate 2 is blocked. Each case is checked and graded once on this path, and final typed-result aggregation equals the existing batch payload.

Refreshed against origin/main 3293550b (merged activity PR #1071) without conflicts. The two proof cases plus existing IFEval aggregate tests pass (15 tests). All Engine gates passed on this base: append-only tests, lint, formatting, types, layering, full tests and coverage.

Wisdom: production expressions, routes and wire contracts remain unchanged. No hidden cache or alternate scoring algorithm. This establishes feasibility, not production rollout: cached transport, early failure handling and the Client score consumer remain. No existing tests edited and no paid calls.
