---
ticket: OME-1787
stack: screamingface
status: done
started: 2026-10-30
finished: 2026-10-30
---

# picture-benchmarks-notebook — an example notebook that runs every picture Benchmark on the local stack or dev

## Intent

A 2-Case LAB-Bench FigQA run on dev was stopped at 2,862 MiB resident memory against its
2,560 MiB per-run budget, a failure the local stack cannot show (it watches no memory). This
unit adds one example notebook that points at the local stack or dev with one `TARGET`
variable, lists which of the five picture Benchmarks that Engine serves (naming each missing
one with its likely reason), and runs 2 Cases of each served one behind `RUN_EVALUATION = False`, so
the owner can catch picture-path bugs on the target where they happen.

## Planned changes

- `packages/screamingface/scripts/build_notebooks.py`: `_picture_benchmarks_e2e()` + registry
  entry `18_picture_benchmarks.ipynb`.
- `packages/screamingface/examples/18_picture_benchmarks.ipynb`: generated, output-free.
- `packages/screamingface/README.md`: one line in the Examples list.
- This ledger and the OME-1787 mirror, both closed.

## Test plan

- `scripts/check_notebooks.py` (committed notebooks match the builder, no paid default),
  `tests/test_notebook_version_provenance.py` (deterministic build, no outputs, version stamp),
  `tests/test_example_notebooks.py` (every `case.<attr>` the notebook reads exists on
  `CaseResult`) cover the new notebook by enumeration.
- `tests/test_fusion_doc_goldens.py` reads the README; run it after the README line.
- ruff, ruff format and pyright on `build_notebooks.py`; ruff on the generated notebook (CI's
  `ruff check` covers `.ipynb`).
- No live Engine, no paid call: a stub-SDK dry run of the code cells (scratch, not committed)
  checks the free path, the missing-reason branches and the record-and-continue path.

## Acceptance

- `18_picture_benchmarks.ipynb` regenerates byte-identically, is output-free, reads only real
  `CaseResult` attributes, and makes no paid call while `RUN_EVALUATION` is False.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned. Regenerating left every other notebook byte-identical.
- **Commits:** see the PR.
- **Gates:** `check_notebooks.py` exit 0; `test_notebook_version_provenance.py` +
  `test_example_notebooks.py` 33 passed; `test_fusion_doc_goldens.py` 40 passed; ruff, ruff
  format and pyright clean on `build_notebooks.py`; ruff clean on the generated notebook (the
  first draft tripped `PLR0911`, four returns in `run_two_cases`, fixed to three). Full suites:
  pre-push hook and CI.
- **Ids verified:** `inspect-lab_bench_figqa`, `inspect-lab_bench_tableqa` (rows on main);
  `inspect-mmmu_multiple_choice` (row on the open MMMU PR,
  https://github.com/ScreamingFace/screamingface/pull/1589); `inspect-mathvista` (row on the
  open MathVista PR, https://github.com/ScreamingFace/screamingface/pull/1593);
  `inspect-mmmu_open` (the key the MMMU open PR in flight under OME-1477 imports; no row pushed
  yet). Each id is `inspect-<key>` per `imported_benchmark_id` in the Engine's
  `single_shot.py`.
- **Model:** `openrouter/google/gemini-3-flash-preview`, copied from `00_quickstart`; it is a
  seeded OpenRouter model, so the Gateway reads its picture support from OpenRouter's catalogue.
- **Deviations:** the run cells call one helper, `run_two_cases(id)`, which wraps
  `sf.evaluate(MODEL, benchmark=id, limit=2)` in a `sf.ScreamingFaceError` catch so a failing
  Benchmark is recorded and the rest still run. Grading per Benchmark is written in the
  notebook (the Benchmark card carries no grading field), taken from each row's description.
- **Owner-verify:** (1) Run All on the local stack and on dev with `RUN_EVALUATION = False`: no paid
  call, the served/missing list matches the Engine. (2) With `RUN_EVALUATION = True` on dev: 2 Cases
  of each served Benchmark; a memory failure shows as `memory_budget_exceeded` in section 6.
  (3) Once the MMMU open PR lands, confirm its id is `inspect-mmmu_open`.
