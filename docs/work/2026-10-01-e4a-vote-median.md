---
ticket: unfiled   # slug-named ledger; set to OME-N when the issue is filed at PR-open
stack: screamingface
status: done
started: 2026-10-01
finished: 2026-10-01
---

# e4a-vote-median — sf.Vote and sf.Median plus the engine contract pins (OME-1289, unit 5)

## Intent

Ship the first two concrete reducers: `sf.Vote` (plurality, first holder wins) and `sf.Median`
(`nearest` member or the numeric `value`). They compile to the pinned combine spec, rebuild from url4
with `Url4(...).to_python()`, and the engine contract is proven from the SDK-written
`reducer_specs.json` (the engine tests never build a spec by hand). Covers VT-1..VT-14 and the
engine halves of EV-6 and EV-13.

## Planned changes

- SDK src: `reducer.py` (Vote, Median), `__init__.py` (exports), `CHANGELOG.md`, `README.md`,
  `tests/public_surface_snapshot.json` (regenerated).
- SDK tests (new): `tests/_combine_contract.py`, `tests/test_vote_median.py`,
  `tests/test_vote_median_contract_fixtures.py`.
- Engine data (new, SDK-written): `combine_contract/{vote_candidate.url4, model_synthesizer_candidate.url4, reducer_specs.json}`.
- Engine tests (new): `test_combine_vote_median.py`, `test_combine_reducer_candidates.py`,
  `inspect/test_combine_gsm8k_check.py`.

## Test plan

SDK (RED first, skeleton classes with a wrong reduce step and repr "?"): VT-9, VT-10, export and
registry, repr, url4 round trip, from_spec refusals, blank operator, drift guard.
Engine (contract pins, pass at once by design because units 1-3 deliver the behavior): VT-1..4, 6..8,
11, 14 on `run(...)`; VT-5, VT-12, VT-13 (IFEval twin), EV-6, EV-13 end to end; VT-13 on GSM8K in the
inspect lane.

## Acceptance

- Both gates green (append-only: only `public_surface_snapshot.json` offends), inspect test passes
  or skips loudly, repo gate green.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned; nothing unlisted. Data files are written by
  `test_vote_median_contract_fixtures.write_fixtures()`.
- **RED/GREEN:** SDK side was RED for the right reason (assertion on the skeleton's wrong reduce step
  and the "?" repr): `test_vote_compiles_to_pinned_spec`, `test_reprs_are_constructor_calls_that_rebuild_equal_values`
  and `test_url4_round_trip_rebuilds_vote_and_median`. The skeleton already held the real constructors,
  `_from_spec` and registration, so VT-10, the export/registry test, the from_spec refusals and the blank
  operator test passed at once (they pin shape the skeleton shipped). The drift guard was RED (files missing)
  then GREEN after `write_fixtures()`. All engine tests (VT-1..8, 11, 14, VT-5, VT-12, VT-13 twin and GSM8K,
  EV-6, EV-13) are contract pins: GREEN on their first run by design, since units 1-3 deliver the behavior.
- **Commits:** see `git log e4a-sdk-reducer-slot..HEAD` on branch `e4a-vote-median`.
- **Gates:** `screamingface --base e4a-sdk-reducer-slot` with append-only: only offender
  `tests/public_surface_snapshot.json` (expected); with `--skip-append-only`: ALL GREEN. `screamingface-engine`
  with append-only: green (no offender); with `--skip-append-only`: ALL GREEN. Inspect test
  (`uv run --extra inspect pytest tests/unit/inspect/test_combine_gsm8k_check.py`): 1 passed. `repo`: ALL GREEN.
- **Deviations:** none from the behavior spec. Tests import `Reducer` from `screamingface.reducer`
  (pyright rejects `sf.reducer`, as the submodule is not a declared attribute of `sf`).
