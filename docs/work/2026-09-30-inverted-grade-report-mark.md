---
ticket: OME-1439 (+ OME-1400's Engine half)
stack: screamingface-engine + screamingface
status: done
started: 2026-09-30
finished: 2026-09-30
---

# inverted-grade-report-mark — carry the Benchmark-level inverted_grade mark into report.json

## Intent

PR 2 of the OME-1400 stack (spec `docs/spec/2026-09-30-safety-refusal-score.md` §5). A Benchmark
that scores 1 − its eval's grade must be visibly marked for researchers: report.json's
`benchmark` block (and each candidate's copy) says `"inverted_grade": true`, including on
replayed reports. The mark travels on the Engine's Benchmark resource and catalogue entry and on
the run result itself, emitted only when true, so every other Benchmark's wire and report stay
byte-identical.

## Planned changes

- Engine `screamingface_engine/benchmarks/definition.py` — `Benchmark.inverted_grade`, emitted in
  the catalogue entry and resource only when true.
- Engine `screamingface_engine/benchmarks/contract.py` — optional `CandidateResult.inverted_grade`,
  serialized only when true.
- Engine `screamingface_engine/benchmarks/aggregation.py` + `shared_grading/benchmark_aggregation.py`
  — `finalize_candidate_result(inverted_grade=)`, `BenchmarkAggregation.inverted_grade` passed by
  both aggregate faces.
- Engine `screamingface_engine_inspect/single_shot.py` — pass the row's flag to `Benchmark` and to
  `BenchmarkAggregation`.
- SDK `discovery.py` (`BenchmarkInfo.inverted_grade`, `_result_dict` emits when true),
  `_evaluation/benchmark.py` (resource decode), `_evaluation/results.py` (run-result decode,
  cross-check, replay), `CHANGELOG.md`, `tests/public_surface_snapshot.json`.

## Test plan

- Engine: a flipped Benchmark's catalogue entry/resource carry `inverted_grade: true`; an
  unflipped one's are byte-identical (no key). `CandidateResult` omits the key when false and
  emits `true` when set. The imported `xstest_unsafe` aggregate's payload carries it.
- SDK: resource decode reads the key (absent → False, non-bool → invalid); run-result decode
  accepts it as optional, rejects a mismatch with the Benchmark resource, and a replay's
  `BenchmarkInfo` takes it from the result; report.json shows it in the root and candidate
  `benchmark` blocks only when true.
- INVARIANT: an unflipped Benchmark's report.json is byte-identical to before.

## Acceptance

- A normal and a replayed `xstest_unsafe` report.json both carry `"inverted_grade": true` in the
  `benchmark` block; every other Benchmark's report states `false`.
- Engine and SDK gates green.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, plus new tests `apps/screamingface-engine/tests/unit/test_benchmark_inverted_grade.py`
  and `packages/screamingface/tests/test_inverted_grade_report.py`, two lines appended to
  `tests/unit/inspect/test_inverted_grade.py`'s suite, and `docs/tasks/2026-09-30-OME-1439-*.md`.
- **Commits:** `feat(screamingface): mark Benchmarks scored by refusal rate in report.json`
  (PR 2 of the OME-1400 stack).
- **Gates:** `run_gates.py screamingface-engine --skip-append-only` green; `run_gates.py
  screamingface --skip-append-only` green (ruff, format, pyright, pytest + coverage ≥95%,
  notebooks, build, distribution); Engine inspect lane 534 passed, 0 skipped. The append-only
  skip is owner-approved (2026-09-30) for the regenerated public-surface snapshot and the
  `"inverted_grade": False` key added to `test_report.py`'s two exact `benchmark`-block asserts.
- **Deviations:**
  - report.json states the key for EVERY Benchmark (`false` when ordinary), not only when true
    as spec §5 first said: the report's own convention is stable keys (`answer_seed`), and a
    researcher should read `false`, not infer it. The wire still omits the key unless true.
    Spec §5 updated.
  - The Engine's `BenchmarkAggregation` gained the flag (one finalize call serves both
    aggregate faces), rather than threading it through every `aggregate(...)` call.
