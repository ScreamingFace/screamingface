---
ticket: OME-1475
stack: screamingface-engine, screamingface
status: done
started: 2026-10-07
finished: 2026-10-07
---

# ome-1475-pr3-musique-benchmark — serve the MuSiQue-Ans Benchmark (PR 3 of 4)

## Intent

The third slice of the MuSiQue-Ans Benchmark (spec `docs/spec/2026-10-07-OME-1475-musique-ans.md`,
plan section "PR 3"). PR 2 shipped the pure pieces (pins, prompt, reply parser, the copied
official scorer). This PR turns them into a served, registered Benchmark `musique-ans`: Case
Preparation (moved here from PR 2, unchanged), the single-shot definition with its Benchmark
Revision and provenance, the check route that reads the two committed lines, the Case Grade with
three Named Scores (`f1` headline, `exact`, `support_f1`) and the two format flags, the run-level
column means, the new failure code on both sides, the SDK CLI entry, the enumerating tests, and
notebook `15_musique`. No Judge, no grading tokens; no existing Benchmark changes.

## Planned changes

- `apps/screamingface-engine/src/screamingface_engine/benchmarks/musique/`: `prepare.py` (from
  PR 2, unchanged), `case_grade.py`, `runtime.py`, `aggregate.py`, `definition.py` (new)
- `apps/screamingface-engine/src/screamingface_engine/benchmarks/builtins.py`: registration
- `apps/screamingface-engine/src/screamingface_engine/benchmarks/contract.py`:
  `musique_grading_failed`
- `packages/screamingface/src/screamingface/_report_primitives.py`: the same code
- `packages/screamingface/src/screamingface/_runtime/cli.py`: `musique` in `_BENCHMARKS` and
  `_validate_benchmark_output`
- `packages/screamingface/scripts/build_notebooks.py` + `examples/15_musique.ipynb`
- Tests (new): `test_musique_prepare.py` (from PR 2), `test_musique_definition.py`,
  `test_musique_case_evaluation.py`, `test_musique_check_route.py`, `test_musique_aggregate.py`,
  `test_musique_resolution.py`
- Tests (existing, extended): `inspect/test_benchmark_declaration.py`,
  `fixtures/early_grade_compatibility.json`, `test_benchmark_stage_parity.py`,
  `test_failure_classes.py`, SDK `tests/test_runtime_cli.py`

## Test plan

- Definition: every pin, the three prompt template constants and the vendored files' sha256 are
  inside the Revision; routes carry it; the expression parses and calls the Candidate once;
  provenance values and declaration as the plan pins them.
- Check route: a real reply becomes `{answer, support, answer_line, support_line}`; missing
  lines are flags, never a crash; a missing answer record refuses before grading.
- Case Grade envelope: bind/decode round trip; missing or ill-typed verdict fields refused.
- Aggregate: the spec's reply table through the whole scored path — Named Scores key set and
  order, headline equals `score`, run-level column means, flags in metrics, `{musique_id,
  hop_type}` in Case metadata, missing material → `missing_answer_asset`.
- Resolution: the composed expression, resolved in-process against a mocked gateway, sends the
  real paragraphs and question and scores the fixture Case end to end.
- Registration: the enumerating tests include `musique-ans`.

## Acceptance

- Every listed test passes; engine full suite green; inspect lane (declaration, provenance)
  green; ruff, ruff format, pyright, layering clean in both packages; both failure-code
  conformance tests green; `check_notebooks.py` clean. No network call, no model call.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, plus two test files the plan did not name.
  - New, Engine: `musique/{case_grade,runtime,aggregate,definition}.py`; `musique/prepare.py`
    and `tests/unit/test_musique_prepare.py` moved in from PR 2 unchanged; tests
    `test_musique_{definition,case_evaluation,check_route,aggregate,resolution}.py`.
  - Changed, Engine: `benchmarks/builtins.py`, `benchmarks/contract.py`;
    tests `inspect/test_benchmark_declaration.py`, `fixtures/early_grade_compatibility.json`,
    `test_benchmark_stage_parity.py`, `test_failure_classes.py`.
  - SDK: `_report_primitives.py`, `_runtime/cli.py`, `tests/test_runtime_cli.py`,
    `scripts/build_notebooks.py`, new `examples/15_musique.ipynb`.
  - Benchmark Revision `4526c4a0880f45c6`.
- **Commits:** one commit on `OME-1475-pr3-musique-benchmark`,
  `feat(screamingface-engine): serve the MuSiQue-Ans Benchmark with three Named Scores (OME-1475, PR 3 of 4)`.
- **Gates:**
  - Engine (`apps/screamingface-engine`): the targeted list (`test_musique_*`,
    `test_benchmark_deployment`, `test_early_grade_compatibility`, `test_benchmark_stage_parity`,
    `test_builtin_early_score_timing`, `test_failure_classes`, `test_failure_code_conformance`,
    `test_benchmark_display_metadata`) 306 passed · inspect lane (`--extra inspect`:
    `inspect/test_benchmark_declaration.py`, `inspect/test_benchmark_provenance_conformance.py`,
    `test_benchmark_display_metadata.py`, `test_musique_*`) 395 passed · full suite
    `pytest -n auto --dist worksteal` 4,753 passed, 83 skipped · ruff clean · ruff format 766
    files already formatted · pyright 0 errors · `check_layering.py` OK.
  - SDK (`packages/screamingface`): ruff clean · ruff format 333 files already formatted ·
    pyright 0 errors · `test_runtime_cli.py` + `unit/test_failure_code_conformance.py` 67 passed ·
    full suite (`--extra notebook`, `-n auto`) 2,267 passed, 26 skipped ·
    `check_notebooks.py` clean. The notebook was generated, never executed.
- **Deviations:**
  - **The early-grade baseline for `musique-ans` is the OLD-form protocol, not today's.** The
    fixture holds each board's pre-early-grade protocol (captured at origin/main 922d392a), and
    the test proves that old batch path and today's early path give identical results.
    Computing the entry from `benchmark.protocol(n)` would compare today's path with itself.
    MuSiQue never had an old protocol, but its expression is ContractEval's shape exactly
    (today's protocols are byte-identical once the route prefix is swapped, asserted by the
    script that wrote the entry), so its baseline is ContractEval's recorded protocol with the
    route prefix swapped.
  - **`test_builtin_early_score_timing.py` is not edited.** Its `else` branch calls the stage-
    parity `assets()`, whose new `musique` branch prepares the fixture's two Cases, which is
    what the timing test needs; both `musique-ans` timing cases pass.
  - **Two extra test files** beyond the plan's four, ported from ContractEval's suite:
    `test_musique_check_route.py` (the parser meets a real Candidate payload; the record passes
    the envelope validator) and `test_musique_resolution.py` (the OME-1126 guard: the composed
    expression resolved in-process against a mocked gateway). The resolution file's `_assets`
    is the musique bundle the enumerating built-in tests import.
  - **The check route does not read the answer record.** ContractEval's and MedXpert's checks
    load it because their verdict needs gold; MuSiQue's check records only what the reply
    committed and the key is applied once, at grading. A missing record is then the aggregate
    ladder's `missing_answer_asset` (spec F7) rather than a check crash; preflight still
    refuses a bundle with any missing record before spend.
  - **Scorer-file hashes in the Revision are a constant in `definition.py`**
    (`SCORER_FILES_SHA256`), since `vendor/__init__.py` records them only in its docstring;
    `test_musique_definition.py` pins the constant to the vendor test's hashes and the
    docstring, so editing a copied file and its pinned hash still moves the Revision.
    `EXPECTED_CASES` and `DATASET_FILE` are hashed too ("every pin"), and a test fails if a new
    pin in `revision_inputs.__all__` is not a `compute_revision` input.
  - **Checks:** one Check per committed line (`answer`, `support`), each with its score; the
    answer check is MET on an exact match, the support check on support F1 1.0. Evidence
    carries counts, never the gold answer.
  - **Run metrics** add `answer_line_found_rate` and `support_line_found_rate` beside
    `scored_cases` (the plan named the per-Case flags only).
  - **Citation** is written from the TACL article's own first page (vol. 10, pp. 539–554,
    doi 10.1162/tacl_a_00475); the repo README's BibTeX lacks a comma and the volume.
  - **Finding for the notebook, not changed here:** the dev file lists all 1,252 two-hop
    Cases first, and Case ids are positions, so any `limit` up to 1,252 is all 2-hop. The
    notebook says so; the per-hop table fills only on a run past Case 1,252.
  - The notebook regeneration rewrote the version stamp in the 12 existing notebooks
    (`0.1.1.post8` → `0.1.2`, metadata only); those were reverted, not committed.
