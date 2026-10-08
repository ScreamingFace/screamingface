---
ticket: OME-1458
stack: screamingface-engine
status: done
started: 2026-10-08
finished: 2026-10-08
---

# attempts-engine-fold — ask, grade and fold N Attempts per Case (PR 6 of 7)

## Intent

The Engine's spine half of OME-1458 (plan `docs/plan/2026-10-08-OME-1458-attempts-per-case.md`,
PR 6, boxes ① ③ ⑧ ⑨). A Benchmark declares `attempts=N`; the per-Case expression runs the
one-Attempt execution N times (Attempt i ≥ 2 tagged `attempt=i`, which PR 5's egress reads);
the shared marking room grades each Attempt with the Benchmark's own Grading and folds the N
grades per Check; the Case Result carries every Attempt.

## Planned changes

- `apps/screamingface-engine/src/screamingface_engine/benchmarks/definition.py` —
  `BenchmarkDeclaration.attempts`, published only above 1; `ATTEMPTS_KEY`.
- `.../benchmarks/protocol.py` — `preserve_candidate_outcome(attempts=N)`.
- `.../benchmarks/graded_answer.py` — the case-attempts route and decoder.
- `.../benchmarks/contract.py` — `CaseAttempt`, `CaseResult.attempts`.
- `.../benchmarks/shared_grading/case_grades.py` — file an Attempts row per Case.
- `.../benchmarks/shared_grading/attempt_fold.py` — new: the per-Check fold.
- `.../benchmarks/shared_grading/benchmark_aggregation.py` — grade each Attempt, then fold.
- Tests: `test_attempt_fold.py`, `test_case_attempts_contract.py`,
  `test_case_attempts_protocol.py` (new).

## Test plan

- Fold: any Attempt met → 1.0, 42 shown; two grids met by different Attempts → 1.0; first best
  Attempt shown; `met_by_attempts` recorded; a partial Check fails the Case as
  `attempt_grade_not_pass_fail`; a failed Attempt kept, the Case graded from the rest; every
  Attempt failed → Attempt 1's failure; differing Check ids and Named Scores refused; cost
  records move onto each Attempt; one Attempt is not a fold.
- Marking room: each Attempt graded by the Benchmark's hook, then folded; two grids; a
  collected Attempt error kept.
- Wire and cover sheet: absent unless set; round trip; numbering; outcome rules per Attempt;
  no Case-level operations beside Attempts; the SDK decodes the same keys (AST twin); the
  `attempts` key matches the SDK; declaration default, publication and refusals.
- Expression: one Attempt renders as before; Attempt 2 carries the param; the Candidate is
  asked twice; end to end, 41 then 42 scores 1.0 with both Attempts (spec acceptance 2).

## Acceptance

- Spec acceptance 1 (the pinned URL4 hashes and every prior test unmodified), 2, 3, and 7
  (Engine half).

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, except Task 6.5: there is no `test_attempts_end_to_end.py`
  probe Benchmark run end to end. `test_case_attempts_protocol.py` runs the two-Attempt Case
  through a live URL4 node instead, and `test_case_attempts_contract.py` holds the declaration
  tests beside the wire.
- **Commits:** see the PR.
- **Gates:** extra-less `pyright` 0 errors; `pytest tests/unit -n auto`: 4668 passed, 44
  skipped.
- **Deviations:** (1) **A failed Candidate Invocation in any Attempt fails the whole Case**, as
  it does for a one-Attempt Case today; only a failed Grading is kept per
  Attempt (inside that Attempt's envelope). URL4 collects errors only inside `iterate`, which rebinds `$item` and
  `$index` that every Benchmark's own nodes read. This narrows spec F4; the spec's failure
  table and limitations say so. (2) The Attempts of one Case may run side by side (they are
  sibling sources of one expression); Cases still run one at a time, and the joined row keeps
  Attempt order. (3) A Benchmark's missing-case hook that files nothing for one Attempt gives
  that Attempt the finalizer's `case_result_missing` row. (4) **Review fixes.** The cover
  sheet's `attempts` and the expression's `preserve_candidate_outcome(attempts=)` are two
  places a Benchmark we build ourselves writes the number; nothing tied them, so a board could
  declare 2 and ask once. `test_every_benchmark_asks_as_many_attempts_as_it_declares` now
  checks every registered Benchmark; the root fix (the expression reads the declaration) is
  left to the first such Benchmark, ARC-AGI-2 (OME-1476). The Attempts rewrite now raises at
  build when Attempt 2 or later reaches no Candidate Invocation, instead of sending a copy of
  Attempt 1. Only a failed Grading is kept per Attempt: a bare per-Attempt error row is not
  emitted today, and its test says the row is a stand-in.
