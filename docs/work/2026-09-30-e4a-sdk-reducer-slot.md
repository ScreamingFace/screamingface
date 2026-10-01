---
ticket: unfiled   # slug-named ledger; set to OME-N when the issue is filed at PR-open
stack: screamingface
status: done
started: 2026-09-30
finished: 2026-10-01
---

# e4a-sdk-reducer-slot — SDK reducer slot, operator catalog client and combine evidence (OME-1289, unit 4)

## Intent

Let `sf.Fusion(..., synthesizer=<Reducer>)` compile to one `/ensemble/combine/v1` url4 call whose
intent is the canonical combine spec (D-1: no raw `$`, `$` escape). Pin operator names against
the Engine's `GET /v1/operators` catalog (cached per Client, ETag revalidated), recover the reducer
topology from url4, and decode the per-operation `combine` evidence into `CaseOperation.combine`.
Concrete reducers (Vote, Median, ...) are later units; this unit lands only the slot.

## Planned changes

- New SDK modules: `reducer.py`, `_operation_bindings.py`, `combine_evidence.py`,
  `_evaluation/operators.py`, `_evaluation/combine_spec.py`, `_evaluation/combine_evidence.py`.
- Modified SDK modules: `fusion.py`, `recipe.py`, `errors.py`, `client.py`, `url4.py`, `case_result.py`,
  `report.py`, `__init__.py`, `_engine/catalog.py`, `_evaluation/{candidate,compilation,topology,url4,runner,model,results}.py`,
  `_ui/cards.py`.
- Tests (new files only) + `tests/data/*.url4` goldens, `tests/_reducer_fixtures.py`.
- Engine plain data: `combine_contract/two_reducers_candidate.url4` (binding_names.json is in the base).
- `.github/workflows/screamingface-tests.yml` paths, `tests/public_surface_snapshot.json`, `CHANGELOG.md`.

## Test plan

SL-1, SL-2 (CHAR, pass at once by design), SL-3..SL-14, EV-7, EV-8, EV-11, EV-14, EV-6 (SDK half),
plus fixture drift guard. SL-10 engine-pattern assertion lives in its own test and is EXPECTED red
on this branch (unit 3 widens the engine pattern).

## Acceptance

- Gate `run_gates.py screamingface` green except `test_engine_binding_pattern_matches_the_shared_fixture`.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, plus nothing unlisted. The engine plain data file is
  `two_reducers_candidate.url4`; `binding_names.json` is unchanged from the base.
- **Commits:** see `git log caaa882dd..HEAD` on branch `e4a-sdk-reducer-slot`.
- **Gates:** `run_gates.py screamingface --base caaa882dd` with the append-only check: the only offender is
  `tests/public_surface_snapshot.json` (expected). `--skip-append-only`: ruff, format and pyright green;
  pytest red only on `test_engine_binding_pattern_matches_the_shared_fixture` (expected until unit 3 widens the
  engine `_BINDING`) plus one load-dependent flake (`test_evaluation_outcome.py::test_a_callback_exception_aborts...`,
  passes 5/5 alone). The pytest step with that one test deselected: 2182 passed, 26 skipped, coverage 96%.
  `check_notebooks.py` and `uv build` green. `run_gates.py repo`: all green.
- **Deviations:** `sf.Reducer` is NOT exported: the existing `tests/test_public_surface.py` lists `Reducer` among
  names that must stay absent from `sf` (legacy alias guard), and existing tests are append-only. Goldens and the engine
  fixture are read with `.removesuffix("\n")` because the end-of-file hook appends a newline to data files.
