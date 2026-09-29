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
filter. This unit (PR 1 of 3 for OME-1269) adds the task route: the bake hands the eval's own
task function our pinned questions and keeps exactly what it keeps. No board is added here.

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

Ticket acceptance 1, 2 and 3; acceptance 5 by construction (the old path runs when `task`
is None).

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned (three source files, two test files, four docs).
- **Commits:** one squash-ready commit on `OME-1269-task-route-bake`.
- **Gates:** ruff check, ruff format --check, pyright (0 errors), check_layering OK,
  `pytest --cov` 4559 passed / 44 skipped, coverage 93.67%; inspect lane
  (`--extra inspect pytest tests/unit/inspect`) 439 passed (was 419).
- **Free real-data check (no token):** the real importer on
  `inspect_evals.pubmedqa.pubmedqa:pubmedqa` emits a task-route row with 500 cases, and on
  `inspect_evals.onet.onet:onet_m6 --shuffle-seed 1269` one with 397 cases (both crashed with
  "dataset is empty" before). Baking the pubmedqa row from the pinned public data gives 500
  cases, each matching a question in inspect's own load.
- **Deviations:** none in the mechanism. Two findings for PR 2 (the boards):
  1. onet_m6 does not bake yet. 6 of the 397 questions inspect keeps have a target letter
     outside their choices (upstream split the choices wrongly, e.g. id `2021_4_b447`:
     target E, 4 choices). The bake's target check refuses them by case number. The owner
     decides: skip onet_m6, or bake 391 with a named deviation.
  2. onet_m6's solver is `multiple_choice(cot=True)`. The importer does not flag `cot`, so
     its row would render the non-CoT template. PR 2 must handle this.
- **Owner-verify:** none for this PR (no board, no image change).
