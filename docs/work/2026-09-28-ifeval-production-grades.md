---
ticket: OME-932
stack: screamingface-engine
status: done
started: 2026-09-28
finished: 2026-09-28
---
# IFEval production early grades

## Intent
Move canonical IFEval grading into its per-case execution and transport the result into final aggregation, without observer-owned state or repeated grading.

## Planned changes
Versioned typed result envelope and strict ordered decoder; board-bound case-result endpoint; IFEval protocol revision and expression migration; final aggregate consumes grades. Keep public CandidateResult unchanged except the intentional benchmark revision.

## Test plan
Real generated expression with second candidate blocked, counts for check/grade, final payload parity, strict identity rejection, serialized replay without grading, anonymous failures. Existing fixtures migrate only with explicit test-change approval.

## Acceptance
Early canonical case result before case 2 finishes. Single grading, exact final score/evidence/failure parity. Production decoder does not fall back to regrading.

## Outcome
Implemented the production IFEval slice. Engine gates and Client gates are green, including coverage, notebook and distribution checks; the unchanged 50-case replay test passes. Existing tests/fixtures use the user-approved append-only migration exception. The full provisional-score feature remains in progress.

### Verification and review
- User authorized the production protocol migration and continuation. Existing-test edits are restricted to IFEval expression/revision pins and declaring the new grading endpoint in the stage-installation test; behavior assertions remain.
- Production expression: grade 1 exists while candidate 2 is blocked. Passing/failing answers match the entire prior batch payload; one checker call per case.
- Serialized results aggregate without checker or grader execution. Missing/anonymous errors preserve selected positions. Corrupt grades remain fatal rather than becoming ordinary failed cases.
- Original cached 50-case IFEval replay: 0.9184, identical statuses, failure codes and coverage. Only golden revision and expression SHA migrated; recorded model requests/responses untouched. The unchanged replay test passes. Fixture-only companion follows the existing OME-1229 migration process; no new ticket or Client runtime change.
- Gate environment: Engine Python 3.13; Client full gates Python 3.12. An initial interrupted Client run was diagnosed as the existing real reconnect-budget delay, not a regression.
- Wisdom: explicit grade transport avoids observer-owned state and duplicate judging. Scope is IFEval only; no speculative plugin discovery. Benchmark revision isolates the changed internal contract. Full per-case event publication/table updates and all-board rollout remain outside this slice.
