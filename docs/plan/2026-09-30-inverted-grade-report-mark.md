# Plan — carry the inverted_grade mark into report.json (OME-1400 PR 2)

- Spec: `docs/spec/2026-09-30-safety-refusal-score.md` §5 (approved 2026-09-30).
- Ledger: `docs/work/2026-09-30-inverted-grade-report-mark.md`. Stacked on PR #1149.

## Steps

1. **Engine Benchmark** → `Benchmark.inverted_grade: bool = False`; `_metadata()` adds
   `"inverted_grade": True` only when set (like `focus`). Verify: new tests in
   `tests/unit/test_benchmark_inverted_grade.py` red → green; `test_benchmark_foundation`'s exact
   catalogue assertion untouched and green.
2. **Engine run result** → `CandidateResult.inverted_grade: bool = False`, excluded from the payload
   when false; `finalize_candidate_result(inverted_grade=)`; `BenchmarkAggregation.inverted_grade`
   passed by `aggregate` and `aggregate_async` (the verbatim twins stay identical). Verify: same new
   test file.
3. **Engine inspect wiring** → `single_shot_benchmark` passes the flag to `Benchmark(...)` and
   `ImportedBenchmark.aggregation()` passes it to `BenchmarkAggregation`. Verify:
   `tests/unit/inspect/test_inverted_grade.py` (appended): xstest_unsafe's catalogue entry and an
   aggregate payload carry the mark.
4. **SDK** → `BenchmarkInfo.inverted_grade: bool = False` (+ `_result_dict` emits when true);
   resource decode (absent → False, non-bool refused); run-result decode takes it as an optional
   key, cross-checks it against the Benchmark resource on a normal run, and a replay builds its
   `BenchmarkInfo` from it. Verify: new `tests/test_inverted_grade_report.py` red → green; the
   exact report-shape tests in `test_report.py` untouched and green.
5. **SDK public surface** → regenerate `tests/public_surface_snapshot.json`; CHANGELOG entry.
6. **Gates** → `run_gates.py screamingface-engine --skip-append-only` and
   `run_gates.py screamingface --skip-append-only` (owner-approved for the snapshot).
