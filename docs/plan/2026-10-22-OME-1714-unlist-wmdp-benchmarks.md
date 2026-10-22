---
ticket: OME-1714
spec: ../spec/2026-10-22-OME-1714-unlist-wmdp-benchmarks.md
status: implemented
date: 2026-10-22
stack: python (apps/screamingface-engine, packages/screamingface)
branch: OME-1714-unlist-wmdp-benchmarks
---

# Plan: unlist the WMDP Benchmarks

One PR, one ticket (small cross-landing work: Engine code + SDK notebook prose).

## U1 — the mark (Engine core)

- `src/screamingface_engine/benchmarks/definition.py`: `Benchmark.unlisted: bool = False`.
  Not in `_metadata()`, so no wire change (spec R4).
- `src/screamingface_engine/rest/benchmarks.py`: `list_benchmarks` skips `unlisted` Benchmarks;
  `get_benchmark` unchanged (spec R1, R2).
- Test `tests/unit/test_benchmark_unlisted.py` (extra-less): default is listed; the list omits
  an Unlisted Benchmark; the resource still answers; the listed neighbour's entry is identical
  with and without the Unlisted sibling; no `unlisted` key on the wire.

## U2 — the three rows (inspect plugin)

- `src/screamingface_engine_inspect/benchmarks.py`: `BenchmarkSpec.unlisted: bool = False`;
  the three WMDP rows set `unlisted=True` with a comment naming OME-1714; the factory threads
  it to `single_shot_benchmark`.
- `src/screamingface_engine_inspect/single_shot.py`: `single_shot_benchmark(unlisted=...)`
  passes it to `Benchmark`. Not a revision pin (spec R4).
- Test `tests/unit/inspect/test_unlisted_rows.py`: the Unlisted set read from the spec rows is
  exactly the three WMDP keys (no assembly, so it runs extra-less); with the extra, the
  assembled WMDP-Bio Benchmark is unlisted and gsm8k is not.

## U3 — SDK notebook prose

- `packages/screamingface/scripts/build_notebooks.py`: drop the three ids from "The rest of the
  shelf"; regenerate `examples/12_inspect_evals_benchmarks.ipynb`.

## U4 — docs

- `CONTEXT.md`: define **Unlisted Benchmark**.
- Ledger, task mirror (done at PR-open), this plan and the spec.

## Verification

- Engine: `tests/unit/test_benchmark_unlisted.py`, `tests/unit/inspect/test_unlisted_rows.py`,
  `tests/unit/inspect/test_published_revisions.py`, `tests/unit/test_benchmark_origin.py`;
  ruff + pyright on touched files; extra-less pyright + `tests/unit` per the CI rule.
- SDK: `uv run --extra notebook python scripts/check_notebooks.py`.
