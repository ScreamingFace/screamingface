---
ticket: OME-1094
stack: screamingface
status: in_progress
started: 2026-09-03
finished:
---

# OME-1094 — Pin each failed case's failure code in the e2e goldens

## Intent

The golden compares only the status word per case. All five rubric failure reasons
(`missing_rubric_asset`, `missing_case_row`, `case_error`, `incomplete_verdicts`,
`no_positive_points`) collapse to `failed`, so the `OME-1039` extraction of that ladder
could reclassify every one of healthbench-worst30's 33 failed cases and CI would stay
green. Pin the failure code (and stage) per failed case in the golden and add a "codes"
rung to the compare ladder between statuses and coverage.

## Planned changes

- `packages/screamingface/tests/e2e/harness/goldens.py` — `GoldenFailure` (stage + code,
  vocabulary imported from the SDK), `GoldenReport.case_failures` with a validator (no
  entry on a scored case; ≥1 entry on a failed case; no entry for an unknown case),
  `ActualOutcome.case_failures`, `failure_map()` (the one function both the test lane
  and the bless tool use to read SDK `CaseResult.failures`), the "codes" rung in
  `compare_outcome`, `GoldenMismatch.stage` gains `"codes"`.
- `packages/screamingface/tests/e2e/fixtures/slice_snapshot.py` — `author_golden` writes
  `case_failures`; both bless flows feed it from the verified replay; new
  `--refresh-golden` mode replays the COMMITTED snapshot and rewrites the golden with
  the failure map, refusing when expression / statuses / counters / score differ from
  the committed file.
- `packages/screamingface/tests/e2e/test_boards.py` — feeds `failure_map(candidate.cases)`.
- `packages/screamingface/justfile` — `e2e-refresh-golden` recipe.
- `packages/screamingface/tests/e2e/README.md` — the new rung + the refresh command.
- `fixtures/goldens/draco-3pass.golden.json` — gains `case_failures: {}` (all scored;
  deterministic from the statuses, no replay needed).
- `fixtures/goldens/healthbench-worst30.golden.json` — needs the docker replay
  (`just e2e-refresh-golden healthbench-worst30`); owner runs it.

## Test plan

- `test_harness_contracts.py`: a flipped code fails at stage `codes` before coverage,
  naming the case id and both codes; matching codes pass; a scored case with an entry
  is refused at load; a failed case without an entry is refused at load; an entry for
  an unknown case is refused at load; an ungraded refused case may carry grading
  failures; `failure_map` reads SDK `CaseResult` values (failed → entries, scored → none).
- `test_bless_contracts.py`: `author_golden` pins the map sorted and the document
  validates; a failed case without a code refuses authorship.

## Acceptance

- The ladder is expression → cases → codes → coverage → score.
- draco-3pass golden lists no failures; the healthbench golden refuses to load until
  refreshed, with a message naming the refresh command.
- Relevant unit tests + ruff + pyright green on the package.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, plus `tests/e2e/test_report_tape.py` (its fusion-golden
  fixture pins a failed case; it now carries a code, see Deviations). The Before/After
  diagram is deliberately NOT committed — owner decision: it lives in the PR description
  only, so the repo carries no diagram asset for this unit.
- **Commits:** `feat(screamingface): pin each failed case's failure code in the e2e goldens`
  (one commit on `OME-1094-golden-failure-codes`; sha in the PR + Linear close comment).
- **Gates:** relevant free lanes only, per owner instruction — `uv run ruff check tests/e2e`,
  `uv run ruff format --check tests/e2e`, `uv run pyright tests/e2e` (0 errors),
  `uv run pytest tests/e2e -q` → 90 passed, 16 skipped (docker-gated). The full
  `run_gates.py screamingface` and the docker replay were NOT run.
- **Deviations:**
  - Two prior test FIXTURES gained a `case_failures` entry (`test_bless_contracts.py::
    test_author_golden_keeps_a_scoreless_run_null`, `test_report_tape.py::
    _fusion_golden_document`). Both pin a `failed` case by status alone, which is exactly
    the shape the new validator refuses; the tests' own intent (scoreless run stays null;
    fusion lineup round-trips) is unchanged. Flagged in the PR for the reviewer.
  - `healthbench-worst30.golden.json` is NOT re-blessed here: docker is not running on
    this machine and the owner asked for unit tests only. Until the owner runs
    `just e2e-refresh-golden healthbench-worst30`, the golden refuses to load (message
    names the command) and the e2e replay workflow is red for that board.
  - Added a `--refresh-golden` bless mode + `just e2e-refresh-golden` (the ticket's "the
    harness just has to write them into the golden … refuse if the score differs").
