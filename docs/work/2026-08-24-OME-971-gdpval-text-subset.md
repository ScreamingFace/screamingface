---
ticket: OME-971
stack: screamingface-engine
status: in_progress
started: 2026-08-24
finished:
---

# OME-971 — Onboard the GDPval text subset as a rubric-graded benchmark

## Intent

GDPval appears in frontier-model launch tables, so a fusion-beats-solo result on it carries
weight our current benchmark set cannot buy. Its official metric — blinded expert pairwise win
rate against a human professional's deliverable — is not reproducible here. But every task in
the open gold subset ships `rubric_json` (median 47 scored criteria, `required` null
throughout), which is the same per-item checkmark family as `healthbench-worst30`. This unit
onboards the prose-only slice of that subset so the existing rubric-judging machinery can grade
it, with no code execution, no sandbox and no artifact handling.

## Baseline re-verified against origin/main @ 443113b4 (2026-08-24)

The planning document was written against a checkout 20 commits stale. Four carried-in
assumptions were re-checked at the branch base; three had already changed.

- **RETIRED — the 1 MiB truncation defect is fixed.** OME-892 replaced truncation with a
  three-way fork in `runner/executor.py::build_result`: inline under
  `DEFAULT_RESULT_INLINE_CAP_BYTES` (524,288), otherwise spill the COMPLETE body to a
  content-addressed artifact store, otherwise refuse with `result_too_large` as a FAILED
  terminal event — "never cut". This unit is NOT blocked; the blocked-by on OME-971 should be
  removed.
- **RETIRED — full HealthBench already shipped.** `HEALTHBENCH_PROFESSIONAL` is registered
  beside `HEALTHBENCH_WORST30`, sharing one asset bundle. No separate ticket needed.
- **CHANGED — benchmarks register through a deployment.** `BUILTIN_DEPLOYMENT` composes
  `BenchmarkRegistration(benchmark=..., asset_bundle=BenchmarkAssetBundle(id=..., prepare=...))`;
  assets build via `benchmarks/prepare.py::prepare_builtin_assets`. Two identities may share one
  bundle — the precedent to follow if a second GDPval board is added later.
- **NEW — artifact storage exists.** `screamingface_engine/artifacts/` provides writer/reader
  ports with filesystem and S3 backends (f9c3f795). Unused here; material for the later
  file-deliverable phase.

Also: `apps/url4-cloud` is now `apps/screamingface-engine`, package `screamingface_engine`
(9b888579). All planned paths below reflect that.

## Planned changes

- `apps/screamingface-engine/src/screamingface_engine/benchmarks/gdpval/__init__.py`
- `.../gdpval/definition.py` — `GDPVAL_TEXT` identity, judge pin, revision hash
- `.../gdpval/exam.py` — `ASSET_BUNDLE_ID`
- `.../gdpval/subset.py` — frozen 102-task id list + sha
- `.../gdpval/prepare.py` — `prepare(out)`: bake cases + rubric assets
- `.../gdpval/ingestion.py` — pdf/docx → text, build time only
- `.../gdpval/rubric_filter.py` — format-criteria filter
- `.../gdpval/prompts.py`, `verdict.py`, `scoring.py`
- `.../gdpval/case_evaluation.py`, `aggregate.py`, `runtime.py`
- `.../benchmarks/builtins.py` — register `GDPVAL_TEXT` + `GDPVAL_ASSETS`
- `apps/screamingface-engine/tests/unit/test_gdpval_{prepare,definition,grading,aggregate,check_surface}.py`

## Test plan

RED first, per `sdlc-python`.

- `prepare`: frozen id-list drift fails the build; re-running over the same revision is
  byte-identical; a reference extracting below the viability threshold fails loudly rather than
  baking an empty reference.
- `definition`: the revision hash changes when any of dataset revision, preparer revision,
  frozen id list, judge pin, or filter revision changes.
- `grading`: each rubric item judged independently; a malformed judge reply is retried, then the
  case marked failed; the format filter removes the expected criteria BEFORE scoring.
- `scoring`: points earned over positive points available, negatives subtract, `required`
  ignored; all judge calls failing yields `score = None`, never `0.0`.
- `aggregate`: `coverage` is the exact graded fraction; `case_count` equals the selected count.

## Acceptance

- `gdpval-text` registered and served with `case_count = 102` and a pinned revision hash;
  `sf.evaluate(model, benchmark="gdpval-text")` returns per-case rubric scores.
- Format-checking criteria filtered before scoring; a failed judge yields `score = None`.
- Benchmark description states the subset rule and that scores are not comparable to OpenAI's
  published win-rate.
- Gates: `ruff check`, `ruff format --check`, `pyright`, `check_layering.py`, `pytest --cov=screamingface_engine
  --cov=url4.streaming --cov-fail-under=80`.

## Measurements from Phase 0 (2026-08-24, recomputed from the published parquet, no model spend)

- Rubrics on 220/220 tasks; criteria min 14 / median 47 / max 137; 10,453 total; `required` is
  `None` on every one; weights mostly +1 (5,369) or +2 (4,341); 94 negative.
- Text subset per the extension filter `{.docx,.doc,.txt,.md,.pdf,""}` (a task with no files
  counts as passing): **109** tasks — 83 expecting a prose deliverable FILE, 26 with none.
- Reference files in the subset: 85 (44 PDF, 41 DOCX) across 43 tasks; **66 of the 109 tasks
  have no reference files at all**.
- Extraction sweep over all 85 (pdfplumber + python-docx): 77 clean, 6 near-empty (scanned-image
  PDFs, an embedded-logo docx), 2 `XMLSyntaxError`. At task level: 102 clean, 5 partially
  degraded, 2 total loss → **this unit ships 102 tasks and documents the 7**.
- Frozen 102-task list sha256
  `2ea8c0d88ebbde08a3456e482d63f3a86a671c3db6785a844b7ba69358c50eb7`.
- After the format filter the 102 tasks carry **4,498 criteria** (raw 4,553; 55 filtered),
  min 13 / median 44 / max 83 per task, 7,183 positive points; 9/9 sectors, 37/44 occupations.
- **Cost consequence:** the HealthBench pattern fans out ONE judge call per rubric item
  (`healthbench/runtime.py::rubric_tasks` renders a `grader_prompt` per item), so a full run is
  ~4,498 judge calls per candidate — roughly 44x the per-task judging the planning document's
  cost model assumed. Must be measured in the pilot before any full run.

## Progress

### Task 1 — frozen selection, pins, and the container filter (DONE)

- **Actual files:** `benchmarks/gdpval/{__init__,subset,rubric_filter}.py`,
  `tests/unit/test_gdpval_{subset,rubric_filter}.py`. `pins.py` deferred to Task 5, where the
  judge pin is first needed — nothing in Task 1 reads it.
- **Gates:** ALL GATES GREEN — ruff check · ruff format --check · pyright · check_layering ·
  pytest --cov-fail-under=80. 2,028 passed, 6 skipped; 14 new tests, no prior test touched.
- **Deviations:**
  - **The filter design changed mid-task, on owner decision.** The planned filter was a bare
    keyword match on format markers. A hand audit against all 4,553 criteria of the 102 selected
    tasks showed it deleting SEVEN content criteria — including a -10 penalty — because a
    REFERENCE filename ended in `.docx`, and missing an unknown number of container criteria
    phrased without those markers. Replaced with a three-rule container-vs-content test
    (strip quoted spans → require a format token → discriminate delivery from content).
    Measured: 99 removed, 209 of 7,183 positive points, zero false positives across a full audit
    of all 99; three known misses (~6 points) pinned in the tests. Spec D3 and F5 updated.
  - `test_gdpval_rubric_filter.py` was REWRITTEN rather than appended to. Same uncommitted
    cycle, design changed by owner decision, and the replacement is strictly stronger: every
    fixture is now a real criterion copied from the published rubrics, since invented fixtures
    were how the first filter passed its tests while deleting real criteria.
  - The shipped module was re-run against the published parquet to confirm it reproduces the
    prototype's measurements exactly (99 / 209). Prototype-to-production drift here would have
    silently changed the answer key.

### Task 2 — build-time reference extraction (DONE)

- **Actual files:** `benchmarks/gdpval/ingestion.py`, `tests/unit/test_gdpval_ingestion.py`.
- **Gates:** ALL GATES GREEN. 8 new tests, no prior test touched.
- **Deviations:**
  - **The reader is INJECTED rather than imported directly.** `pdfplumber` and `python-docx` are
    build-time only — absent from the runtime AND the test environment, exactly as `datasets` is
    for the other preparers — so a module that imported them directly could not be unit-tested at
    all. The policy (viability floor, error identification, determinism) takes a `reader`
    callable; `pdf_reader()` / `docx_reader()` are thin adapters exercised only at image build.
    This is the hexagonal rule in CLAUDE.md applied to a dependency boundary that already existed.
  - **`MIN_VIABLE_CHARS = 200` is derived, not guessed.** Measured over all 85 reference files of
    the 109 prose-only tasks: the six unusable extractions clustered at 0, 0, 0, 0, 81 and 106
    characters; the smallest genuine extraction was 261. Any threshold in (106, 261] separates the
    two populations. A test asserts the constant stays inside that interval, so a later retune
    cannot drift to a number nobody can re-derive.
  - `extract_reference_text` catches broadly and re-raises as `IngestionError`. Deliberate and
    annotated: readers fail in library-specific ways (python-docx raises XMLSyntaxError for a
    malformed package), and what the operator needs is WHICH of 85 files broke. The original
    exception is preserved as the cause.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** <vs planned>
- **Commits:** <sha — message>
- **Gates:** <run_gates.py result line / counts>
- **Deviations:** <anything that differed from the plan, or "none">
