---
ticket: OME-1527
stack: screamingface-engine
status: done
started: 2026-10-14
finished: 2026-10-14
---

# run-verdict-counts — the lane adds up each Case's judge-verdict counts so the grading warning fires again

## Intent

OME-1527 Work order row 18b. The Report warns "Grading did not fully land" when a judge's
replies never parsed; it reads the Candidate metrics `verdicts_rejected` / `invalid` /
`missing` (and `verdicts_expected` for "of N verdicts"). The hand-built DRACO grader summed
them from each Case; since draco moved to a local inspect Task (row 18, #1395) the shared
lane's run tally never added any counts up, so the warning could not fire for draco (a known
limitation recorded in `2026-10-13-draco-local-task.md`, item 6). This restores it once, for
the whole lane, without editing draco's Task (its revision and the draco-3pass golden stay).

## Planned changes

- New `apps/screamingface-engine/src/screamingface_engine_inspect/verdict_counts.py`: the
  convention (a scorer writes `verdicts_expected` + `verdicts_accepted` in `Score.metadata`),
  `case_verdict_counts` (check them, derive `verdicts_rejected`) and `run_verdict_counts`
  (sum over graded Cases).
- `scorer_adapter.py`: copy a graded Case's checked counts onto its grade metrics; bad counts
  fail the Case as `invalid_score_value`.
- `single_shot.py` `_accuracy`: add the summed counts to the run metrics (the whole-run tally
  reads `_accuracy`'s metrics, so it inherits them).

## Test plan

- New `tests/unit/inspect/test_run_verdict_counts.py`: draco-3pass over the canned Cases →
  18 expected / 16 accepted / 2 rejected, and the SDK Report's own `_grading_html` (lifted
  from its source by AST, no cross-app import) renders "2 rejected of 18 verdicts"; a clean
  run → rejected 0, no warning; a row whose scorer counts nothing → metrics unchanged; a
  whole-run-metric row sums too; six bad-count shapes fail the Case by name.
- Mutation: drop the run sum → the spec test goes red.

## Acceptance

- The draco warning renders from run metrics; no other imported row's metrics change; draco's
  Task source, revision and golden untouched.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned (3 src files, 1 new test file, this ledger). No pre-existing
  test edited, so no `.claude/test-change-approvals/OME-1527.json` change.
- **Mapping (hand-built → lane):** hand-built per Case: `rejected` = expected − accepted,
  `invalid` = replies with no usable verdict, `missing` = no reply at all (so rejected =
  invalid + missing). The lane publishes `verdicts_expected`, `verdicts_accepted` and
  `verdicts_rejected` (same formula); it does not publish `invalid` / `missing`, since two
  counts cannot split the shortfall. For draco every shortfall IS an unparsed reply (a failed
  judge call fails the whole Case as `scorer_error`), so the hand-built Report said
  "2 rejected · 2 invalid of 18 verdicts" where the lane's now says "2 rejected of 18
  verdicts" — the same count, one label fewer.
- **Failed Cases:** add nothing, as the hand-built `draco_scorer` summed graded Cases only.
  One difference: an abstained Case whose judge never gave a verdict is kept at 0.0 (OME-1289)
  with no counts here, where the hand-built grader kept its zeroed counts (all rejected).
- **Golden:** `draco-3pass.golden.json` pins final score, statuses, failures, revision and
  expression hash only — no metrics — and no judge request changes, so it replays unchanged;
  nothing re-recorded.
- **Tests run (inspect extra):** `test_run_verdict_counts.py` (10), `test_local_task_draco.py`,
  `test_local_task_gdpval.py`, `test_whole_run_metric.py`, `test_scorer_metrics.py`,
  `test_inspect_single_shot.py`, `test_inspect_scorer_adapter.py` — 115 passed. Mutation
  (drop the `run_verdict_counts` line in `_accuracy`): 3 tests red, restored in place.
  `ruff check` / `ruff format --check` clean on touched files; extra-less `pyright` 0 errors.
- **Deviations:** the brief's example derived `verdicts_missing = expected − accepted`; that
  formula is the hand-built `rejected`, and `missing` meant "no reply at all", so the lane
  publishes `rejected`. gdpval's `judge_invalid_replies` is still not restored (its scorer
  writes no verdict counts; decision 1).
