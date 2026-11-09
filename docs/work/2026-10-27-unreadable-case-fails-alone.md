---
ticket: OME-1271
stack: screamingface-engine
status: done
started: 2026-10-27
finished: 2026-10-27
---

# unreadable-case-fails-alone — one Case the grader can't read fails by name, not the whole run

## Intent

PR 4 of 5 for OME-1271, found in review on 2026-10-23. The scorer adapter rebuilt each Case's
chat before its per-Case error handling, so a Case whose input breaks the envelope rules raised
out of the aggregate and no Case of the run got a grade. That Case should fail alone, by name.
Nothing we generate writes such a Case (the importer builds Cases from inspect's own messages),
so this guards a hand-written or hand-edited Cases file. Opening a picture from its Case Result
is PR 5.

## Planned changes

- `apps/screamingface-engine/src/screamingface_engine_inspect/scorer_adapter.py`: the chat
  rebuild in `grade()` catches `CandidateInputError` and fails that Case as
  `invalid_candidate_input`; a `TypeError` (our wiring) still raises.
- `apps/screamingface-engine/src/screamingface_engine_inspect/single_shot.py`: one failure
  message row for `invalid_candidate_input`.
- `apps/screamingface-engine/tests/unit/inspect/test_unreadable_case_fails_alone.py` (new).

## Test plan

- Three Cases, the middle one unreadable (a `developer` turn, which the connector's reader admits
  and the scorer's refuses). At the hook: Cases 1 and 3 score, Case 2 fails as
  `invalid_candidate_input` naming the rule, and the scorer never marks it. Through the real
  aggregate with the plugin's failure wording: Cases 1 and 3 are graded, Case 2 fails alone.

## Acceptance

- One unreadable Case fails by name and the run's other Cases still grade.
- The existing tests that expect a `TypeError` on a wiring fault still pass unchanged.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, plus this ledger.
- **Commits:** fix(screamingface-engine): fail only the Case the grader can't read, not the whole
  run; docs: this ledger renamed and closed when PR 4 was split from the picture work.
- **Gates:** relevant tests only, inspect extra: `test_inspect_scorer_adapter.py` +
  `test_unreadable_case_fails_alone.py`, 38 passed. Both new tests fail on the unfixed adapter (the
  raise escapes the aggregate); the aggregate test fails with `KeyError: 'invalid_candidate_input'`
  without the message row. ruff check, ruff format --check, pyright clean on the touched files.
- **Deviations:** the ledger was written after the code, not before. PR 4 first also planned the
  picture work; it was split out to PR 5 on 2026-10-27 so this fix can merge on its own.
