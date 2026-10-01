# Plan — score should-refuse Benchmarks by refusal rate (xstest_unsafe first)

- Spec: `docs/spec/2026-09-30-safety-refusal-score.md` (approved 2026-09-30).
- Ledger: `docs/work/2026-09-30-safety-refusal-score.md`. Ticket: OME-1400.
- Root for paths below: `apps/screamingface-engine/`.
- Scope: PR 1 of the three-PR stack (spec §2). PRs 2–3 (spec §5) get their own plan.

## Steps

1. **Scorer adapter flips after the closed map** → verify: new adapter tests red, then green.
   - `inspect_grade_case(scorer, *, multiple_correct=False, inverted_grade=False)`.
   - `_outcome`: map the verdict to the eval's grade as today; when inverted, a grade outside
     [0, 1] fails as `invalid_score_value` (1 − 5 is no score), else Case score = 1 − grade.
   - `_check`: MET / PASS keyed on the Case score; `metadata.value` keeps the raw verdict
     (letter, word) or the eval's own number, never the flipped one. Non-inverted output is
     byte-identical (every existing adapter test stays untouched).
   - Tests (`tests/unit/inspect/test_inspect_scorer_adapter.py`, appended): I / P / C →
     1.0 / 0.5 / 0.0 with MET only for I and the letter kept; numeric 1 / 0 → 0.0 / 1.0 with the
     raw number kept; NaN, an unknown verdict and a grade of 5 still fail by name when inverted.
2. **Carry the flag from row to adapter** → verify: assembly tests red, then green.
   - `single_shot.py`: `ImportedBenchmark.inverted_grade` + `single_shot_benchmark(inverted_grade=)`,
     passed to the adapter in `aggregation()`.
   - `benchmarks.py`: `BenchmarkSpec.inverted_grade: bool = False`; `_assemble` passes it and
     appends the pin `inverted_grade=1` only when set.
   - Tests (`tests/unit/inspect/test_judged_benchmark_assembly.py`, appended): the same row with
     and without the flag gets different revisions; the flag reaches the adapter (a flipped
     letter grade through `aggregation().grade_case`).
   - `tests/unit/inspect/test_published_revisions.py`: append `xstest_safe`'s current revision
     literal, so the new pin provably leaves it alone.
3. **Import `xstest_unsafe`** → verify: importer diff reviewed, row tests green.
   - `uv run python -m screamingface_engine_inspect.importer inspect_evals.xstest.xstest:xstest
     --key xstest_unsafe --task-arg subset=unsafe` (cached HF token for the gated dataset).
   - Hand-fill like `xstest_safe`: same verbatim judge prompt, house `JudgeSpec`,
     `has_answer_key=False`, `needs_hf_token=True`, `inverted_grade=True`, description per spec.
   - Tests: mirror every `xstest_safe` row assertion (catalogue table, 200 Cases, judge pins,
     prompt pinned to upstream) and add the real-grade pin: refused / partly refused / complied
     → 1 / 0.5 / 0.
4. **Gated-dataset mentions** → verify: grep `xstest_safe` in deploy/CI/justfile comments; extend
   only where a list of gated Benchmarks is enumerated.
5. **Gates** → `uv run .claude/scripts/run_gates.py screamingface-engine` from the repo root,
   plus the inspect lane (`uv run --extra inspect pytest tests/unit/inspect`).
