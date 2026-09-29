---
ticket: OME-1269
stack: screamingface-engine
status: done
started: 2026-09-29
finished: 2026-09-29
---

# inspect-task-route-bake — bake the exact questions an inspect eval keeps after loading

## Intent

Three inspect evals (onet_m6, pubmedqa, xstest) drop questions after loading. Today the
importer crashes on them with "dataset is empty", and the bake has no way to run their
filter. This unit (PR 1 of 3 for OME-1269) adds the question-filter step: the bake hands the eval's own
task function our pinned questions and keeps exactly what it keeps. It also ships the first
question-filter board, `onet_m6` (owner widened the scope; see Deviations).

## Planned changes

- `apps/screamingface-engine/src/screamingface_engine_inspect/prepare.py`
- `apps/screamingface-engine/src/screamingface_engine_inspect/boards.py`
- `apps/screamingface-engine/src/screamingface_engine_inspect/importer.py`
- `apps/screamingface-engine/tests/unit/inspect/test_inspect_snapshots.py`
- `apps/screamingface-engine/tests/unit/inspect/test_inspect_importer.py`
- docs: spec, plan, this ledger, `docs/tasks/` mirror

## Test plan

See the plan, steps 1 and 4.

## Acceptance

Ticket acceptance 1, 2 and 3; acceptance 5 by construction (the old path runs when `question_filter_task`
is None).

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, plus `pins.py` and the two board-registry tests for the
  `onet_m6` board (owner widened the scope on 2026-09-29).
- **Commits:** two on `OME-1269-task-route-bake` (mechanism; onet_m6 board + CoT +
  named exclusion).
- **Gates:** ruff check, ruff format --check, pyright (0 errors), check_layering OK,
  `pytest --cov` 4575 passed / 44 skipped, coverage 93.66%; inspect lane 453 passed (419
  before this unit).
- **Free real-data checks (no token):** the real importer writes a question-filter row for
  `pubmedqa` (500 cases) and for `onet_m6` (397 cases); both crashed with "dataset is empty"
  before. The production bake (`prepare_snapshot`) of the committed `onet_m6` row gives 391
  cases: 391 unique ids, equal to inspect's own 397 minus the 6 excluded ids, with the same
  input, target and choices for each. The prompt leads with the eval's language note and has
  inspect's CoT wording.
- **Deviations:** scope widened by the owner to ship `onet_m6` in this PR, with
  `cot=True` support and the named exclusion (6 questions whose answer letter points past
  their last choice). After a naming review, the mechanism's own names moved to the
  question-filter vocabulary before merge (`question_filter_task` / `question_filter_task_args`,
  `filters_after_load`), so no house word lands that OME-1404 would later rename.
- **Owner-verify:** a paid smoke run of `onet_m6` is the owner's to press.
