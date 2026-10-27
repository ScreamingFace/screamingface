---
ticket: OME-1271
stack: screamingface-engine
status: in_progress
started: 2026-10-27
finished:
---

# pictures-on-demand — open a picture from its Case Result, and one unreadable Case fails alone

## Intent

PR 4 of OME-1271. After PR 3 (#1558) a Case Result shows each picture as a placeholder, so a
researcher needs a way to open one picture on request, checked against the placeholder's sha256.
This PR also carries the grading fix found in review on 2026-10-23: the scorer adapter rebuilt a
Case's chat before its per-Case error handling, so one Case whose input breaks the envelope rules
raised out of the aggregate and no Case of the run got a grade. That fix is one commit, first.

## Planned changes

- Grading fix (commit 1):
  - `apps/screamingface-engine/src/screamingface_engine_inspect/scorer_adapter.py`: the chat
    rebuild in `grade()` catches `CandidateInputError` and fails that Case as
    `invalid_candidate_input`; a `TypeError` (our wiring) still raises.
  - `apps/screamingface-engine/src/screamingface_engine_inspect/single_shot.py`: one failure
    message row for `invalid_candidate_input`.
  - `apps/screamingface-engine/tests/unit/inspect/test_unreadable_case_fails_alone.py` (new).
- Pictures on demand: to be planned (engine route serving one part by Benchmark revision + Case
  id + message index + part position; SDK show-picture action verifying the sha256).

## Test plan

- Grading fix: three Cases, the middle one unreadable (a `developer` message, which the
  connector's reader admits and the scorer's refuses). At the hook: Cases 1 and 3 score, Case 2
  fails as `invalid_candidate_input` naming the rule, and the scorer never marks it. Through the
  real aggregate with the plugin's failure wording: Cases 1 and 3 are graded, Case 2 fails alone.
- Pictures on demand: to be planned.

## Acceptance

- One unreadable Case fails by name and the run's other Cases still grade.
- OME-1271 acceptance 8: from a picture Case's result, a researcher opens one picture, fetched on
  request and verified against the placeholder's sha256.

## Outcome (fill at the end — required before COMMIT)

- **Actual files (grading fix):** as planned.
- **Commits:** grading fix — fix(screamingface-engine): fail only the Case the grader can't read,
  not the whole run.
- **Gates (grading fix):** relevant tests only, inspect extra: `test_inspect_scorer_adapter.py` +
  `test_unreadable_case_fails_alone.py`, 38 passed. Both new tests fail on the unfixed adapter (the
  raise escapes the aggregate); the aggregate test fails with `KeyError: 'invalid_candidate_input'`
  without the message row. ruff check, ruff format --check, pyright clean on the touched files.
- **Deviations:** the ledger was written after the grading fix's code, not before.
