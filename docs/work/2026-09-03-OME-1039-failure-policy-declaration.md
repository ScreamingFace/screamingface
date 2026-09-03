---
ticket: OME-1039
stack: screamingface-engine
status: done
started: 2026-09-03
finished: 2026-09-03
---

# OME-1039 — Declare failure policy + interaction type; extract the shared failure ladder

## Intent

First code PR of the OME-1024 spine chain. Two moves: (1) every Benchmark registers a
required, typed declaration record (`failure_policy` + `interaction`) with no defaults,
surfaced in catalog/resource output, so the scoring policy is approvable from the manifest
before the spine collapse makes it a hidden default; (2) extract the five-rung failure
ladder duplicated verbatim (modulo comments/kwargs style) between `gdpval/aggregate.py`
and `healthbench/aggregate.py` into a new `benchmarks/spine/` module — the first brick of
the spine. draco/ifeval untouched (their folds are later tickets). `aggregation.py` and
`contract.py` untouched (live-progress branches OME-932/OME-934 own them).

## Key finding (deviation from ticket narrative)

The ticket's Before-section claims ifeval/draco are "all-or-nothing" (withhold). The code
says otherwise: all four boards route through the shared `finalize_candidate_result`
(`aggregation.py:71`), which scores exactly the gradeable subset and publishes coverage —
uniform **coverage_declare** behavior. The declaration must tell the truth (that is the
whole point of the ticket), so **all six builtins declare `coverage_declare`**; `withhold`
stays a valid enum value with no current claimant. Flagged in PR + Linear comment.

## Planned changes

- `src/screamingface_engine/benchmarks/definition.py` — add `BenchmarkDeclaration`
  (frozen dataclass: `failure_policy: "withhold"|"coverage_declare"`,
  `interaction: "single_shot"`; named ValueError on any other value); `Benchmark` gains
  required field `declaration` (no default, positioned before defaulted fields);
  `_metadata()` emits both values (→ catalog_entry + resource).
- `src/screamingface_engine/benchmarks/spine/__init__.py` (new package)
- `src/screamingface_engine/benchmarks/spine/grading.py` (new) — `CaseGrader` class
  holding the shared rungs: `case_result`, `_terminal_failure_outcome`, `_scored_outcome`,
  `_missing_row_outcome`, `_failed_result`, `failure`, `_failure_metadata`,
  `_source_error`. Board-varying bits injected at construction: `failure_messages`
  mapping, `case_score`, `verdicts`, `checks`, `candidate_fields` callables. Failure
  codes + message texts stay byte-identical per board (messages are board-supplied).
- `src/screamingface_engine/benchmarks/gdpval/aggregate.py` — build module-level
  `CaseGrader`, delete the 8 copied functions.
- `src/screamingface_engine/benchmarks/healthbench/aggregate.py` — same.
- Board definitions add declarations: `ifeval/definition.py`, `gdpval/exam.py`,
  `healthbench/exam.py`, `draco/exam.py` (all `coverage_declare` + `single_shot`).
- Test fixtures constructing `Benchmark`: `tests/unit/test_benchmark_deployment.py`,
  `test_benchmark_display_metadata.py`, `test_benchmark_foundation.py` — add the new
  required field (mechanical; mandated contract change, not test weakening).

## Test plan (RED first)

- `tests/unit/test_benchmark_declaration.py` (new):
  - omitting `declaration` → construction fails (registration impossible before any paid request)
  - bad `failure_policy` value → named ValueError
  - `interaction="multi_turn"` → named ValueError (refused before any paid request)
  - `catalog_entry()` and `resource()` carry `failure_policy` + `interaction`
  - every builtin declares; all six pinned `coverage_declare` (invariant: declaration
    matches `finalize_candidate_result` reality)
- `tests/unit/test_spine_case_grader.py` (new): one test per rung through the shared
  module — missing_rubric_asset, missing_case_row (orphan `collected_errors` attached),
  case_error, incomplete_verdicts, no_positive_points — plus scored + refused happy paths
  and message-text-comes-from-injected-mapping.
- All existing tests stay green unmodified (except the three fixture files above).

## Acceptance

- Benchmark without `failure_policy`/`interaction` cannot be constructed/registered.
- Both values appear in catalog + resource output; no spine-level default exists.
- The five-rung ladder exists once; gdpval + healthbench call it; per-case failure codes
  and message texts byte-identical (goldens' codes rung proves it in CI).
- Engine gates green. Diff ≲ 400 lines target.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, plus `benchmarks/__init__.py` (re-export
  `BenchmarkDeclaration`) and a payload-pin update in
  `test_benchmark_foundation.py::test_list_is_complete_metadata_and_detail_is_an_exact_selection`
  (the catalog now carries the two declared fields — the ticket's own acceptance).
  New tests: `test_benchmark_declaration.py` (8), `test_spine_case_grader.py` (8).
- **Commits:** single commit on `OME-1039-failure-policy-declaration` —
  `feat(screamingface-engine): declare failure policy + interaction per benchmark; extract shared failure ladder`.
- **Gates:** `run_gates.py screamingface-engine --skip-append-only` ALL GREEN
  (ruff check, format, pyright, layering, pytest 2302 passed / 5 skipped, cov ≥80%).
- **Deviations:**
  - Ticket's Before-narrative (ifeval/draco "all-or-nothing") is stale: all four boards
    reduce through shared `finalize_candidate_result` = uniform coverage_declare. All six
    builtins declare `coverage_declare`; `withhold` has no claimant. Linear comment posted.
  - Append-only test gate: 3 fixture files construct `Benchmark` and mechanically needed
    the new required field; 1 test pins the exact catalog payload and gained the two new
    fields. Both forced by the mandated contract change — ran the gate with its
    `--skip-append-only` flag; no assertion was weakened.
  - Client SDK checked: `_decode_benchmark_resource` reads field-by-field (`.get`), no
    strict schema — additive manifest fields are safe, no compat PR needed.
  - Pre-review polish (owner-requested): class renamed CaseLadder → `CaseGrader`
    (responsibility-named; "ladder/rung" stays as docstring vocabulary), module
    `spine/case_ladder.py` → `spine/grading.py`; manifest value normalized to snake_case
    `coverage_declare` before it froze into the contract (engine wire vocabulary is
    snake_case everywhere else).
