---
ticket: OME-932
stack: screamingface-engine
status: done
started: 2026-09-28
finished: 2026-09-28
---
# Incremental canonical case results

## Intent
Prove a shared incremental grading interface for OME-932 before wiring provisional score publication. This draft is a prerequisite, not the completed table feature.

## Planned changes
Expose ScoredPath.iter_case_results, consuming the same row validation and grading path as final aggregation. Make aggregation consume this iterator. Keep missing-result finalization unchanged. No Client or expression changes.

## Test plan
Append tests showing a typed result is available before the next grader runs, no repeated grading, and existing final aggregation parity. Run Engine gates.

## Acceptance
One shared canonical path; no duplicate grader or observer-owned execution. Existing boards retain final results and errors. Clearly document that earlier built-in case execution and structured score publication remain.

## Outcome
Implemented the shared async iterator and made final aggregation consume it. Six new tests cover early yield, cancellation by closure, up-front row validation, failure results, omitted cases and single grading per selected case.

Validation: RED demonstrated the missing interface; all Engine gates passed via run_gates.py (lint, format, types, layering, full tests and coverage). FrontierScience's eight board tests passed with the Inspect extra and fake judge route. No existing test was edited. No paid calls.

Wisdom review: no parallel grader, extra dependency, public wire schema, expression or client change. The interface performs grading explicitly and exposes no logging side effects. Existing board hooks and final missing-case reconciliation remain authoritative.

Historical scope at this step (superseded by the all-benchmark live-score ledger): this was a draft prerequisite. Early built-in grade production, cumulative structured snapshots, all-board incremental acceptance and Client table updates are unfinished. OME-932 remains In Progress. The all-board runtime matrix in the plan has not yet been run.
