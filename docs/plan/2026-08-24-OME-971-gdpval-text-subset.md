# OME-971 — GDPval text subset implementation plan

> **For agentic workers:** work task-by-task; steps use `- [ ]`. The stack loop is `sdlc-python`.

**Goal:** Serve `gdpval-text` — 102 prose-only GDPval gold tasks, graded per rubric item by the
existing judge chain — with no code execution, no sandbox and no artifact handling.

**Architecture:** A new `benchmarks/gdpval/` package mirroring `benchmarks/healthbench/`: pinned
inputs in `pins.py`, a frozen selection in `subset.py`, build-time reference extraction in
`ingestion.py`, a format-criteria filter applied during `prepare`, and one board declared through
a `gdpval/exam.py` template. Registration is one `BenchmarkRegistration` in `BUILTIN_DEPLOYMENT`.

**Tech Stack:** Python 3.12+ · uv · pytest · pyright · ruff

**Spec:** `docs/spec/2026-08-24-OME-971-gdpval-text-subset.md`
**Ledger:** `docs/work/2026-08-24-OME-971-gdpval-text-subset.md`

## Global constraints

- **Gates (from repo root):** `uv run .claude/scripts/run_gates.py screamingface-engine` —
  `ruff check` · `ruff format --check` · `pyright` · `check_layering.py` ·
  `pytest --cov=screamingface_engine --cov=url4.streaming --cov-fail-under=80 -q`
- **Tests are append-only.** Never weaken or delete a prior test; modifying one is a 95%-gate STOP.
- **Commit body carries** `Refs: OME-971`. Never `Co-Authored-By`. Never commit to `main`.
- **Files stay ≤450 lines.**
- **Semantic anchors only:** `WHY:` `INVARIANT:` `AIDEV-NOTE:` `FEATURE:` `STORY:`.
- **Runner Jobs are offline with a read-only disk.** Nothing may fetch or parse at run time; all
  extraction happens in `prepare`.
- **`score = None`, never `0.0`,** when no numeric grade exists. The `CandidateResult` contract
  already forbids turning infrastructure failure into a plausible zero.
- **No new dependency in the runtime import graph.** `pdfplumber` / `python-docx` are
  build-time only, imported lazily inside `prepare`, exactly as DRACO imports `datasets`.

## File structure

| File | Responsibility |
|---|---|
| `gdpval/pins.py` (create) | dataset + revision, judge model/params/retries, preparer + filter revision |
| `gdpval/subset.py` (create) | frozen 102 `task_id`s, the 7 exclusions with reasons, `subset_sha()` |
| `gdpval/rubric_filter.py` (create) | format-criteria predicate + `FILTER_REVISION` |
| `gdpval/ingestion.py` (create) | pdf/docx → text, viability threshold; build time only |
| `gdpval/prepare.py` (create) | `prepare(out)` → `cases.json` + `rubrics/<case>.json` |
| `gdpval/scoring.py` (create) | `case_score`, `mean` — pure arithmetic |
| `gdpval/prompts.py` / `verdict.py` / `records.py` (create) | grader template, reply parsing, record binding |
| `gdpval/exam.py` (create) | `gdpval_benchmark(...)` → `(Exam, Benchmark)`; revision, routes, url4 tree |
| `gdpval/definition.py` (create) | the `gdpval-text` board — one call to `gdpval_benchmark` |
| `gdpval/runtime.py` / `case_evaluation.py` / `aggregate.py` / `check_policy.py` (create) | the protocol routes |
| `benchmarks/builtins.py` (modify) | add `GDPVAL_ASSETS` + one `BenchmarkRegistration` |

---

## Task 1: Frozen selection, pins, and the format filter

Pure data and predicates — no I/O, no network. Establishes the identity this board is addressed by.

- [ ] RED `test_gdpval_subset.py`: the frozen list holds exactly 102 ids; the 7 exclusions are
      absent and each carries a documented reason; `subset_sha()` is stable and changes if any id
      changes.
- [ ] RED `test_gdpval_rubric_filter.py`: the predicate flags the known format criteria
      (`.docx` / `.xlsx` / `.pptx` / "excel workbook" / "file format" / "basename") and leaves
      content criteria alone; filtering the baked fixture removes exactly 55 criteria worth 113
      positive points.
- [ ] GREEN `pins.py`, `subset.py`, `rubric_filter.py`.

**Watch:** the filter is a keyword heuristic. Record in `rubric_filter.py` that it is
approximate, and that a criterion it misses penalises every candidate equally rather than
silently favouring one.

## Task 2: Build-time reference extraction

- [ ] RED `test_gdpval_ingestion.py`: a text-bearing PDF and DOCX extract above threshold; a
      zero-text PDF and a malformed DOCX (`XMLSyntaxError`) each raise a named build error
      identifying the task and file; extraction is deterministic across repeated runs.
- [ ] GREEN `ingestion.py` with lazy `pdfplumber` / `python-docx` imports.

**Watch:** the viability threshold is a judgement call. Phase 0 measured 6 files under 200
characters against 77 above it, with the nearest survivor far clear — but state the number and
its evidence in the module, so a later reader can re-derive it rather than guess.

## Task 3: Prepare — bake cases and rubrics

- [ ] RED `test_gdpval_prepare.py`: baking a pinned fixture emits `cases.json` with 102 entries
      and one rubric asset per case; a drifted id list fails loudly; a second run over the same
      revision is byte-identical; filtered criteria are absent from the baked rubrics.
- [ ] GREEN `prepare.py` — fetch pinned rows, select, extract references, filter criteria, emit.

**Watch:** reference text joins the prompt under a stable delimiter in dataset file order. That
ordering is part of the answer key — vary it and two runs of the same board differ.

## Task 4: Scoring and judge-reply parsing

- [ ] RED `test_gdpval_scoring.py`: points earned over positive points available; negatives
      subtract; `required` is ignored; a case with no numeric grade yields `None`; the exam mean
      is a plain mean over graded cases.
- [ ] RED `test_gdpval_verdict.py`: a well-formed judge reply parses; a malformed one raises so
      the retry path can see it; an exhausted retry marks the case failed rather than scoring it.
- [ ] GREEN `scoring.py`, `verdict.py`, `prompts.py`, `records.py`.

## Task 5: The exam template and the board

- [ ] RED `test_gdpval_definition.py`: `case_count == 102`; the revision changes when any of
      dataset revision, preparer revision, filter revision, protocol revision, scoring name or
      selection sha changes; routes hang under `/benchmarks/gdpval-text/<revision>/`; the judge
      model resolves in the declared model world.
- [ ] GREEN `exam.py`, `definition.py`.

**Watch:** follow HealthBench and expose the board as exactly two names — the `Exam` and the
`Benchmark`. Reach routes through `GDPVAL_TEXT_EXAM.routes.*`, never a module-level alias.

## Task 6: Protocol routes and registration

- [ ] RED `test_gdpval_grading.py`: `rubric-tasks` fans out one grader prompt per surviving
      criterion; the full record rides the first task only.
- [ ] RED `test_gdpval_aggregate.py`: `coverage` is the exact graded fraction; `case_count`
      equals the selected count; a candidate with no numeric grade has `score is None` and
      `coverage == 0`.
- [ ] RED `test_gdpval_check_surface.py`: the paid-check disclosure is declared and surfaced
      before paid work begins.
- [ ] GREEN `runtime.py`, `case_evaluation.py`, `aggregate.py`, `check_policy.py`; register
      `GDPVAL_ASSETS` + `BenchmarkRegistration` in `builtins.py`.

## Task 7: Close

- [ ] Full gate run from repo root.
- [ ] Fill the ledger Outcome section — actual files, commits, gate counts, deviations.
- [ ] Commit with `Refs: OME-971`; open the PR; close the Linear issue with the card's
      `close_template` and close the `docs/tasks/` mirror.

## Deliberately deferred

- The five-task pilot's paid measurements (judge cost at ~44 calls per case, chunking behaviour
  at the 83-criterion worst case). Needs model spend and a running stack; not a code task.
- The 23 spreadsheet-reference tasks and the 88 artifact tasks — later phases.
- `justfile` wiring for local asset prep, once `prepare` exists and its runtime is known.

## Execution record (filled during implementation)
