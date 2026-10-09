---
ticket: OME-1527
stack: screamingface-engine
status: done
started: 2026-10-09
finished: 2026-10-09
---

# OME-1527-pr2-whole-run-metric — score a run with the eval's own whole-run metric when the row opts in

Work order #2 of OME-1527 (R1, plus R2 "honour"). PR 2 of 20, stacked on #1323.

## Intent

An Imported Benchmark's score is always the mean of its Case scores: the tally is hard-wired to
`_accuracy`. Some evals score the whole run with their own inspect `@metric` (contracteval's F1
over a confusion matrix, ifeval's pooled instruction accuracy, HLE's calibration error), and
the mean of those Cases is a different number. This unit lets a Benchmark row opt in to the
eval's own metric: the scorer adapter keeps each graded Case's raw inspect `Score` in memory
for the run, and the tally rebuilds inspect's `SampleScore`s and calls the eval's metric. The
default stays the mean, so no published row or revision moves. The importer gets a
per-Benchmark choice for a non-mean headline (honour the metric, or keep the mean under a
Named Deviation), which makes xstest_safe/unsafe, coconot_original/contrast and bbeh
re-importable again with their published rows unchanged.

## Planned changes

- `screamingface_engine_inspect/scorer_adapter.py`: an optional per-run store; every graded
  Case's headline `SampleScore` lands in it, keyed by Case id.
- `screamingface_engine_inspect/single_shot.py`: `ImportedBenchmark` carries an optional
  metric factory; the aggregate builds one store per call and tallies with the eval's metric
  when set (`_accuracy` otherwise). The revision pin is the caller's.
- `screamingface_engine_inspect/benchmarks.py`: `BenchmarkSpec.whole_run_metric` (a dotted
  `module:constructor` reference, omitted when unset), its revision pin only when set, and an
  assembly refusal of `inverted_grade` together with it.
- `screamingface_engine_inspect/scorer_metrics.py`: the dotted reference of an honourable
  headline metric, or why it cannot be honoured.
- `screamingface_engine_inspect/importer.py`, `import_replay.py`, `task_replay_rows.py`: the
  `--whole-run-metric honour|mean` choice, carried into the import child; `honour` writes the
  reference, `mean` writes a `# NAMED DEVIATION:` line; no choice keeps today's refusal.
- Tests: new files under `tests/unit/inspect/`.

## Test plan

- The tally: a contracteval-shaped fake Task whose metric is F1; "no related clause" on a
  70%-no-clause run scores 0.7 as the mean and 0.0 as F1. A dict metric, a raising metric and an
  unreduced metric are refused by name. Failed Cases stay out. A non-finite or above-1 headline
  is refused by name.
- The store: concurrent grading (asyncio.gather) keeps each Case's own Score; a failed Case
  leaves nothing; no store means nothing is kept.
- The row: unset → no pin, no published row opts in (every existing revision literal holds);
  set → its own pin; inverted grade + metric refused at assembly.
- The importer: honour writes the reference; mean writes the Named Deviation line and no
  duplicate TODO; no choice still refuses; a choice on a mean headline is refused; grouped /
  argument-bearing metrics are refused for honour, by name. The five published rows import
  with `mean` against their real metric objects.

## Acceptance

- A row that opts in publishes the eval's own whole-run number; every other row is unchanged.
- No published revision moves.
- xstest_safe/unsafe, coconot_original/contrast and bbeh import again with the mean kept.
- Free inspect unit lane green; extra-less pyright clean on the touched files.

## Outcome

- **Actual files:** as planned, plus `test_whole_run_metric.py` and
  `test_importer_whole_run_choice.py` (new). No prior test edited.
- **Size:** about 1,064 added lines (about 407 src + 657 tests) against the ~500 cap. The PR
  was held and a two-PR split proposed (runtime half, importer half); the owner waived the
  cap for this PR only and it opened as ONE draft PR, both commits as they were.
- **Commits:** `56bf0a2d4` feat(screamingface-engine): score a run with the eval's own
  whole-run metric when the row opts in; `ddb0a58eb` feat(screamingface-engine): let the
  importer honour or keep the mean for a non-mean whole-run metric; plus this ledger's close.
- **Gates:** `run_gates.py screamingface-engine` ALL GATES GREEN; `tests/unit/inspect` 1340 passed (1315 on the base + 25 new); plugin-adjacent
  unit tests 103 passed; ruff check + format clean; extra-less pyright on the touched files
  0 errors.
- **Re-import proof (free, network, no model call):** xstest_safe/unsafe,
  coconot_original/contrast and bbeh re-imported with `--whole-run-metric mean` into a
  scratch copy: every declaration is identical to the published one apart from the licence
  line (owner-filled, not a revision input), so the Case Digests and pins match; the
  generated rows add one `# NAMED DEVIATION:` comment and no field.
- **Decisions taken:**
  - Memory, not Grading Material: the plugin lane grades every Case inside its one
    aggregate call; the incremental consumer (`shared_grading/incremental.py`, OME-932) is
    used only by the hand-built boards. One store per aggregate call, keyed by Case id.
  - The tally replays inspect's default `mean` reduction per Case before the metric, as
    inspect does at one epoch; a Task with its own epoch reducer (coconot, HLE) is refused
    for honour.
  - An honoured metric is written `TODO:<reference>`; assembly refuses the prefix until a
    reviewer confirms the metric is higher-is-better up to 1 (inspect metrics declare
    neither range nor direction). The tally refuses a headline above 1 or non-finite.
  - `whole_run_metric` with `inverted_grade` or `verdict_grades` is refused at assembly.
  - `whole_run_metric` without `keep_sample_metadata=True` is refused at assembly; an honour
    import keeps the metadata, so a metric never reads an empty dict.
- **Deviations:**
  - The keep-the-mean Named Deviation is a comment, not a revision pin (CONTEXT.md says a
    Named Deviation is included in the Revision); pinning it would move five published
    revisions, which the brief forbids.
- **Owner-verify:** which of the five rows, if any, should honour the eval's metric (none can
  today: xstest's `refusal_rate` is 0..100 and lower-is-better on xstest_safe, coconot has
  its own reducer, bbeh's headline is `grouped(...)` built with arguments); whether to
  support a declared scale or direction (see the PR's Known limitations).
