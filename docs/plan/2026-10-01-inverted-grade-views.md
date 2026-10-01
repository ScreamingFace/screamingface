# Plan — show the inverted_grade mark in the catalogue and the notebook report (OME-1400 PR 3)

- Spec: `docs/spec/2026-09-30-safety-refusal-score.md` §5. Ticket: OME-1439. Stacked on PR #1157.
- Ledger: `docs/work/2026-10-01-inverted-grade-views.md`. Root: `packages/screamingface/`.

1. **Catalogue decode** → `_BenchmarkEntry.inverted_grade` (absent → False, non-bool refused via
   `_catalog_invalid`); `Benchmark.inverted_grade: bool = False`; `_benchmark()` passes it.
   Verify: new `tests/test_inverted_grade_views.py` red → green.
2. **Listing + card** → `benchmarks_rows_html` adds `_chip("inverted grade")` with a plain hover
   title; `benchmark_card_html` adds a wide `grading` field ("Inverted — each Case scores 1 − the
   eval's grade, so higher is still better"). Only when true. Verify: same test file; existing
   catalogue tests untouched and green.
3. **Report view** → `_head_html` adds one `sf-report__sub` line with the same sentence when
   `report.benchmark.inverted_grade`. Verify: same test file, through a real `evaluate` report.
4. **Public surface + CHANGELOG** → regenerate the snapshot (`Benchmark` gains a defaulted field).
5. **Gates** → `run_gates.py screamingface --skip-append-only` (owner-approved for the snapshot).
