---
ticket: OME-932
stack: screamingface-engine
status: done
started: 2026-09-28
finished: 2026-09-28
---
# Early-grade transport design

## Intent
Resolve the production transport direction after the test-only IFEval early-grade proof.

## Planned changes
Document explicit typed-result transport, board binding, failure/selection validation, replay and accounting constraints. No runtime changes.

## Test plan
Inspect current row validation, finalization, accounting reconciliation and connector cache handling. Document executable acceptance tests for implementation.

## Acceptance
A concrete proposal that preserves final-result authority and does not depend on observation state, with migration scope and unproven behavior explicit.

## Outcome
Added docs/spec/2026-09-28-early-grade-transport.md. Source review favors a versioned typed row carried through normal execution, observed for provisional scores. Accounting remains final-run reconciled. No production implementation or runtime guarantee claimed; original OME-932 scope must be revised before the protocol migration. Documentation-only; diff whitespace check passed.
