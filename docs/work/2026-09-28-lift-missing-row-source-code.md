---
ticket: OME-1390
stack: screamingface-engine
status: done
started: 2026-09-28
finished: 2026-09-28
---

# lift-missing-row-source-code — a missing row reports its real cause at the top

## Intent

On the shared scored path (every board except the ones with their own missing-row hook), a Case
whose row was lost to a collected error is published as `missing_case_row`, with the real code
(`model_token_cap`, `provider_error`, …) buried in `metadata.source_error.code`. IFEval already
publishes the real code at the top. Lift the source error's code onto the Failure's top-level
`code` on the spine's default missing-row rung, so readers of the top-level code (reports, the
paid smoke) see the real cause.

Owner decisions (2026-09-28, recorded on OME-1390):
- lift ANY declared source code (the error normaliser already folds unknowns into `upstream_error`);
  a source error with no code keeps `missing_case_row`;
- missing-row rung only — `case_error` is out of scope;
- keep `metadata.source_error` (kind, retryable, source_code stay audit material);
- stage stays `candidate` (the candidate-vs-grading boundary is OME-981's).

## Planned changes

- `apps/screamingface-engine/src/screamingface_engine/benchmarks/spine/scored.py` — the default
  missing-row rung publishes the source error's public code; docstrings updated.
- `apps/screamingface-engine/tests/unit/test_spine_scored.py` — new tests: lifted code, no-code
  orphan keeps `missing_case_row`, unknown code lifts as `upstream_error`.
- e2e goldens (`packages/screamingface/tests/e2e/fixtures/goldens/`) — regenerate any whose
  missing rows carried a coded source error; IFEval golden byte-identical.
- `docs/tasks/2026-09-28-OME-1390-missing-row-real-cause.md` — mirror.

## Test plan

- RED: an orphan carrying `code: model_token_cap` → Failure code `model_token_cap`, stage
  `candidate`, `metadata.source_error.code == model_token_cap`.
- An orphan with no code → `missing_case_row` (prior tests already pin this; must stay green).
- No orphan at all → `missing_case_row` with the board message.
- An orphan with an undeclared code → `upstream_error`, spelling kept in `source_error.source_code`.
- A wrapped `provider_error` still reads as a failure (status failed, code `provider_error`).
- e2e replay lane for ifeval, gdpval-text, healthbench-worst30.

## Acceptance

- Token-exhausted Case on the shared path reports `model_token_cap` top-level; pinned by a test.
- Missing row with no underlying source error still reports `missing_case_row`.
- IFEval golden byte-identical; other affected goldens regenerated in the same PR.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** `spine/scored.py` (the lift + docstrings), `spine/rows.py` (worked-example
  docstring), `tests/unit/test_spine_case_grader.py` (3 new tests; ladder tests live there, and
  `test_spine_scored.py` is already past the 450-line cap), goldens `gdpval-text` +
  `healthbench-worst30` refreshed, ledger, mirror.
- **Commits:** see branch `OME-1390-lift-missing-row-source-code`.
- **Gates:** `run_gates.py screamingface-engine` ALL GREEN (append-only check passed, no prior
  test touched); `run_gates.py screamingface --skip-append-only` ALL GREEN; e2e replay lane
  16 passed / 3 skipped (boards with no fixtures, same as main).
- **Deviations:** the two goldens moved 38 failed-case codes `missing_case_row` →
  `upstream_error` via `just e2e-refresh-golden` (statuses, counts, scores unchanged; the tool
  refuses otherwise). The replay's failed cases are deliberate cache-miss holes, so the lifted
  code is the replay's `profile_not_found` 404 folded to `upstream_error`, not the paid run's
  original cause (never recorded). Owner approved `--skip-append-only` for exactly these two
  golden files (2026-09-28). IFEval + draco goldens byte-identical. Test file choice:
  `test_spine_case_grader.py` instead of the planned `test_spine_scored.py` (size cap).
