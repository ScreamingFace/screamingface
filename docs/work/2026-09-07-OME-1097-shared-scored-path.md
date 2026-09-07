---
ticket: OME-1097
stack: screamingface-engine
status: in_progress
started: 2026-09-07
finished:
---

# OME-1097 — Share the scored path and scorer for rubric benchmarks behind a `grade_case` hook

## Intent

Third code PR of the OME-1024 spine chain. The scored path — orchestrate selected cases,
run the failure ladder, mark each case against its rubric, fold marks into the exam
result — exists near byte-identically in `gdpval/aggregate.py` (322 lines) and
`healthbench/aggregate.py` (376 lines). This unit moves it into `benchmarks/spine/`
behind one per-board async hook, `grade_case`, whose typed signature is the epic's
public seam (enclave judge, inspect_evals shim, agentic boards all consume it). Both
`aggregate.py` files are deleted; each board keeps a small hook module. The kind-tagged
payload types deferred by OME-1096 are introduced here (`kind: "text"` only; the full
vocabulary is OME-1103's decision).

## Planned changes

All paths relative to `apps/screamingface-engine/`.

- NEW `src/screamingface_engine/benchmarks/spine/payloads.py` — `TextPayload`
  (kind-tagged, frozen, serializable); `CasePayload` union of one member today.
- NEW `src/screamingface_engine/benchmarks/spine/scored.py` — `CaseGradeOutcome` (plain
  data: score, metrics, checks, optional failure), `GradeCase` async hook type,
  `rubric_grade_case(...)` factory (the shared rubric marking: verdict matching,
  completeness, checks/evidence projection — absorbed from the boards' `_verdicts` /
  `_checks` / `_evidence`), the shared `aggregate` orchestration (selected-cases reader,
  RowReader, failure ladder, hook call, result assembly, finalizer), and the shared exam
  scorer parameterized by the board's `mean` (owning `sample_stdev` /
  `verdict_coverage`).
- MODIFY `src/screamingface_engine/benchmarks/spine/__init__.py` — export the new seam.
- MODIFY `src/screamingface_engine/benchmarks/spine/grading.py` — the ladder stays; its
  board-hook plumbing rewires to the new hook boundary (extent settled during RED).
- NEW `src/screamingface_engine/benchmarks/gdpval/grade.py` +
  `src/screamingface_engine/benchmarks/healthbench/grade.py` — board hook modules:
  `AggregateError`, failure-message wording, judge producer id, `load_rubric_points`,
  `grade_case` bound from the board's `case_score`, and a thin `aggregate` binding so
  runtime/tests swap one import.
- DELETE `src/screamingface_engine/benchmarks/gdpval/aggregate.py` and
  `src/screamingface_engine/benchmarks/healthbench/aggregate.py`.
- MODIFY `src/screamingface_engine/benchmarks/gdpval/runtime.py` +
  `.../healthbench/runtime.py` — aggregate import moves to the board's `grade.py`.
- Board `scoring.py` files: `case_score` and `mean`s stay board-owned (gdpval's
  scoring.py carries an explicit WHY against collapsing the per-case math);
  `sample_stdev` / `verdict_coverage` move to the spine scorer, board copies removed as
  orphans, their direct tests' imports updated to the production location.
- Tests: existing `test_healthbench_aggregate.py` / gdpval aggregate-path tests keep
  every assertion, imports move to the new entry point; NEW spine hook-contract tests;
  NEW gdpval metric-key byte-identity pin (ticket requirement — gdpval has no golden).
- Zero edits to draco, ifeval, `aggregation.py`, `contract.py`.

## Test plan

- RED first: spine hook-contract tests — a stub `grade_case` receives payloads + grading
  material as plain data (no Path, no engine objects) and its returned grade lands in
  the CaseResult; failure-ladder codes byte-identical per board wording table; async
  hook awaited from the sync aggregate handler.
- gdpval metric-keys pin: `pass_rate, scored_cases, score_sd, verdict_coverage,
  judge_invalid_replies` byte-identical (its only net — no golden until OME-1098).
- All pre-existing aggregate/scoring/runtime tests pass with assertions unmodified.
- Full engine suite + gates (`run_gates.py screamingface-engine`).

## Acceptance

- `grade_case` exists, typed; both rubric boards implement it in hook modules under
  ~150 lines each; both `aggregate.py` files deleted.
- One scored path and one exam scorer in the repo; rendered expressions untouched.
- Diff under ~800 lines, else split per ticket instruction.
- healthbench-worst30 golden green on every rung (e2e lane).

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, with three placement deviations: the shared rubric
  marking landed as `spine/rubric.py` and the exam scorer as `spine/exam.py` (450-line
  file cap on `scored.py`); `read_selected_cases` landed in `spine/rows.py` (asset
  reading is that module's turf). `spine/grading.py` (`CaseGrader`) deleted — the hook
  seam subsumes it; its 8 ladder tests rewired through `ScoredPath` with every
  behavioral assertion preserved.
- **Commits:** eac8acde — refactor(screamingface-engine): share the rubric scored path
  behind a grade_case hook (PR #847)
- **Gates:** run_gates.py screamingface-engine ALL GREEN (append-only check:
  owner-approved modifications listed under Deviations, run with --skip-append-only);
  unit suite 2352 passed / 5 skipped; e2e golden replays healthbench-worst30 and
  draco-3pass PASSED (all rungs) with locally prepared assets.
- **Deviations:**
  - Found and fixed a latent design bug during GREEN: the url4 node runs the sync
    aggregate handler inside a running event loop, so `asyncio.run` on the async hook
    raises; `_run_sync` bridges via a single-worker thread there (runtime tests caught
    it).
  - Prior-test modifications (assertions preserved, constructions/imports follow the
    moved code): test_spine_case_grader.py (rewired to ScoredPath),
    test_benchmark_declaration.py (finalizer-funnel identity extended to the spine
    path), test_healthbench_aggregate.py / test_grading_error_integrity.py /
    test_benchmark_outcome_conformance.py (import swaps to `grade.py`),
    test_gdpval_scoring.py / test_healthbench_grading.py (stdev/coverage imports moved
    to `spine.exam`).
  - Diff runs over the ticket's ~800-line guideline in gross terms; production code is
    net −50 lines and 857 of the added lines are tests — single PR kept (owner call).
  - Pre-existing, unrelated: 4 setup errors in `tests/e2e/test_replay_plumbing.py`
    (missing local tracer fixtures), present independent of this change.
