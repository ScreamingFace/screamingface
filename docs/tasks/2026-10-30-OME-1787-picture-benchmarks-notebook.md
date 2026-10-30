---
id: OME-1787
linear_url: https://linear.app/openmined/issue/OME-1787/image-support-benchmark-path-add-an-example-notebook-that-runs-every
status: done
type: feature
priority: medium
labels: [client-sf, agentic, autonomous]
parent: OME-1330
created: 2026-10-30
closed: 2026-10-30
---

# IMAGE SUPPORT - BENCHMARK PATH: Add an example notebook that runs every picture Benchmark on the local stack or dev

`packages/screamingface/examples/18_picture_benchmarks.ipynb` points at the local stack or dev
with one `TARGET` variable, lists which of the five picture Benchmarks (LAB-Bench FigQA and
TableQA, MMMU multiple choice and open, MathVista) that Engine serves, names each missing one
with its likely reason (no inspect extra, Case Digest sealed on Linux on a Mac, or not merged
yet), and runs 2 Cases of each served one behind `RUN_EVALUATION = False`.

- Results: per Case status, score and failure codes; one picture fetched with
  `sf.fetch_media(...)` from `case.media`; the judge's evidence on MMMU open.
- A run that fails is recorded with its error code and the next Benchmark still runs; a
  memory failure on dev shows as `memory_budget_exceeded`, naming
  `runnerPool.perRunCharge.memoryLimitMi`.
- Run All is free; nothing starts or stops a stack.

Owner verify: Run All on both targets with `RUN_EVALUATION = False`, then one paid run on dev.

Ledger: `docs/work/2026-10-30-picture-benchmarks-notebook.md`.
