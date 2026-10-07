---
ticket: OME-1268
stack: screamingface-engine
status: done
started: 2026-10-06
finished: 2026-10-06
---

# ome-1268-engine-named-scores — the Engine spine carries Named Scores (PR 3 of 5)

## Intent

The third slice of the OME-1268 stack. The Engine's wire models gain an optional `scores`
field (absent unless set, the `inverted_grade` precedent); the inspect scorer adapter grades a
Case once per declared scorer and reads a dict-valued inspect Score as named values, failing
the Case by name on any undeclared key; the reducer averages every column over the same graded
Cases as the headline; the row declares `extra_scorers`, `named_scores` and `dropped_scorers`,
all pinned into the Benchmark Revision; and a helper classifies a scorer's declared headline
metric as a plain mean or not, for PR 4's importer tripwire. No importer change, no new
Benchmark. Deploys only after PR 2's SDK (#1248) is released.

## Planned changes

- `apps/screamingface-engine/src/screamingface_engine/benchmarks/definition.py`: `SCORES_KEY`
- `.../benchmarks/contract.py`: `CaseGrade.scores`, `CandidateResult.scores`, validators
- `.../benchmarks/aggregation.py`: `CandidateScore.scores`, `finalize_candidate_result`
- `.../benchmarks/shared_grading/benchmark_aggregation.py`: `CaseGradeOutcome.scores`,
  `_scored_result` writes and checks the key set
- `.../screamingface_engine_inspect/scorer_adapter.py`: several scorers, dict-valued Score,
  headline-only flip and word map, one Check per scorer
- `.../screamingface_engine_inspect/single_shot.py`: row fields threaded to the adapter;
  `_accuracy` means every column
- `.../screamingface_engine_inspect/benchmarks.py`: `BenchmarkSpec.extra_scorers`,
  `named_scores`, `dropped_scorers`; `_named_score_pins`; assembly refusals
- `.../screamingface_engine_inspect/scorer_metrics.py` (new): `headline_metric_kind`

## Test plan

- `tests/unit/test_candidate_result_contract.py`: absent-unless-set, finite-or-None values,
  non-empty keys, unscored Candidate carries none; SDK key conformance (AST twin)
- `tests/unit/inspect/test_inspect_scorer_adapter.py`: two scorers grade once each, headline
  column equals `score`, flip and word map on the headline only, one failing scorer fails the
  Case, dict-valued Score → named scores, undeclared / missing key fails by name, single-scorer
  path has no key
- `tests/unit/test_shared_grading_aggregation.py`: `_scored_result` refuses a key set that
  differs from the declared names
- `tests/unit/inspect/test_named_score_pins.py` (new): pins only when set, assembly refusals
- `tests/unit/inspect/test_scorer_metrics.py` (new): accuracy/mean are plain means, stderr is
  ignored, a custom metric is "other"
- `tests/unit/inspect/test_published_revisions.py` unchanged

## Acceptance

- Spec §8 items 3 and 5 (Engine side) and 6; plan Review Focus 2, 3, 4, 5, 7.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned. Changed: `benchmarks/definition.py` (`SCORES_KEY`),
  `benchmarks/contract.py` (`CaseGrade.scores`, `CandidateResult.scores`, `_named_scores`,
  `_unscored_candidate_outcome`), `benchmarks/aggregation.py` (`CandidateScore.scores`),
  `shared_grading/benchmark_aggregation.py` (`CaseGradeOutcome.scores`,
  `BenchmarkAggregation.named_scores`, `_named_scores`), `screamingface_engine_inspect/
  scorer_adapter.py` (`_named_outcome`, `_multi_outcome`, `_dict_outcome`,
  `_dict_shape_problem`, `_check(check_id=)`), `single_shot.py` (`extra_scorer_factories`,
  `named_scores`, `_column_means`), `benchmarks.py` (`BenchmarkSpec` ×3 fields,
  `_check_named_scores`, `_named_score_pins`, `_extra_scorer_factories`). New:
  `screamingface_engine_inspect/scorer_metrics.py`. Tests, all new files (44 tests):
  `tests/unit/test_named_scores_contract.py`, `tests/unit/inspect/test_named_scores_adapter.py`,
  `tests/unit/inspect/test_named_score_pins.py`, `tests/unit/inspect/test_scorer_metrics.py`.
- **Commits:** e3092756b — feat(screamingface-engine): carry a Benchmark's Named Scores
  through grading
- **Gates:** `run_gates.py screamingface-engine` ALL GREEN: append-only, ruff check, ruff
  format, pyright (0 errors with the inspect extra), layering, pytest `-n auto` with coverage
  (5520 passed / 6 skipped on the unit lane; floor 80 met). `test_published_revisions.py`
  untouched and green.
- **Deviations:** (1) the branch is stacked on `OME-1268-sdk-named-scores` (#1248), not on
  `main`: the SDK key twin test reads the SDK's `SCORES_KEY`, which exists only there; retarget
  to `main` after #1248 merges. (2) A dict-valued scorer keeps one Check (id `"1"`) carrying the
  headline key's grade, not one Check per key. (3) An extra scorer is constructed without kwargs.
  (4) `_column_means` returns `None` for a column no graded Case filled, never zero. (5) The
  word map (`verdict_grades`) is the headline scorer's vocabulary only; the other scorers speak
  inspect's letters, so a word there fails the Case by name (spec §2.1 made explicit).
