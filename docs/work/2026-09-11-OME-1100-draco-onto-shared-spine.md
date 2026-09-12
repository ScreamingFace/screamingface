---
ticket: OME-1100
stack: screamingface-engine
status: done
started: 2026-09-11
finished: 2026-09-12
---

# OME-1100 — Fold the draco 5-pass and 3-pass boards onto the shared spine

## Intent

draco (5-pass) and draco-3pass are the last boards on a private spine copy:
`benchmarks/draco/aggregate.py` (484 lines) duplicates row decode and failure
handling that the shared spine already serves to gdpval and healthbench via
the `grade_case` hook (`OME-1097`). This unit routes draco through that hook —
row decode + failure path from the spine, the multi-pass verdict reduction
(N judge passes per criterion: means per axis, pass rates, stddevs, coverage)
staying draco-owned as its `grade_case` and scorer parameter — and deletes
`draco/aggregate.py`. This proves the hook carries a genuinely different
grading shape without a sibling spine (epic OME-1024 exit criterion: five
boards on one spine).

## Planned changes

RESTACKED mid-design onto `OME-1101-ifeval-spine-fold` (PR #913): that branch
already replaced `mean` with a `scorer` parameter and added the board-owned
`missing_row_result` hook — the same seam this unit was about to widen with a
flags dataclass. The flags design was dropped for #913's grammar: board-owned
whole-result hooks. All under `apps/screamingface-engine/` unless noted:

- `spine/scored.py` — `CaseGradeOutcome.metrics: Mapping[str, Any]`;
  `missing_row_result` may return `None` (file nothing → finalizer's
  `case_result_missing`); new optional `error_row_result` (outranks the
  material rung when set) and `missing_material_result` and
  `hook_failure_result` board hooks. Defaults preserve gdpval/healthbench
  byte-for-byte.
- `spine/rows.py` — `RowReader.claim_anonymous_errors: bool = False` (True
  files a positional anonymous error row as that Case's row).
- `draco/grade.py` — NEW hook module: `aggregate()` with the old signature,
  per-call `ScoredPath` (judge_passes-bound decoder + multi-pass `grade_case`
  + the four board hooks), `draco_scorer` + the eight reduction helpers
  (deliberately NOT in `scoring.py`, whose docstring pins isolation from
  aggregation).
- `draco/case_results.py` — `scored_grade`/`incomplete_grade` now return
  `CaseGradeOutcome`; typed-result builders kept only where a board hook needs
  them (`incomplete_case_result`, `ungraded_case_result`, `_case_result`);
  `failed_selected_case_result` + the dead scored branch removed.
- `draco/aggregate.py` — DELETED. `_require_verifiable_mapping` not ported:
  the exact decoder + RowReader position identity make it unreachable, and its
  pinned tests match the RowReader's position-worded aborts.
- `draco/runtime.py` — `_aggregate` calls `grade.aggregate`.
- Tests: import-only repoints in 9 engine test modules + the declaration
  test's mechanism loop (draco moved to the spine-families loop — same class
  of mechanical edit OME-1101 made, owner-approved); one `CaseGrade.model_
  validate` in my own new test for pyright. New spine tests appended to
  `test_spine_scored.py` (6) + `test_spine_row_reader.py` (1). Assertions
  everywhere byte-identical. `packages/screamingface/tests/e2e/test_failures.py`
  docstring pointer updated to `grade.py`.

## Key equivalences verified during design

- Error row → draco shape (upstream code, `{row_index, error_kind}`, grade
  None) reproduced by `upstream_error_rows` + `ladder_failure_grade=False`;
  rung checked before material, matching draco's order.
- Missing row → `omit_missing_rows` lets `finalize_candidate_result` emit
  `case_result_missing` (draco's shape) instead of `missing_case_row`.
- Result metadata: spine merges roll-call `selected.metadata` with the row
  record's metadata — identical to draco's record-only metadata in every
  reachable case EXCEPT the error row (see Deviations (4): pre-fold published
  `{}` there; the fold made error rows carry the cases.json extras like every
  other Case shape — owner-approved, pinned by a new unit test).
- Abort wording: spine's "Case result at position N is invalid: …" satisfies
  every pinned regex ("position N", "claims case_id X, but the selected Case
  is Y", "invalid DRACO Judge Evidence", "Case execution has an invalid shape").
- Scores: `score_case` pre-rounds to 4; spine re-round idempotent.

## Test plan

- Existing suites are the net, append-only: `test_draco_aggregate.py`,
  `test_draco_failure_integrity.py`, `test_draco_3pass_definition.py` stay
  green untouched.
- draco-3pass golden: 100 cases, all scored, score `0.3593`, on every rung.
- Seven authored failure tapes in `tests/e2e/test_failures.py` land exactly
  where they land today.
- New tests only where the hook module introduces new seams.

## Acceptance

- `benchmarks/draco/aggregate.py` gone; draco hook module ~200 lines plus scoring math.
- Rendered expressions untouched.
- Diff under ~800 lines (else split failure-path / scored-path into two PRs).
- All gates green (`run_gates.py screamingface-engine`).

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned (post-restack list above); plus
  `test_benchmark_declaration.py` mechanism loop and the `test_failures.py`
  docstring pointer.
- **Commits:** one squashed commit on `OME-1100-draco-shared-spine`, stacked on
  `OME-1101-ifeval-spine-fold` (PR #913): `refactor(screamingface-engine): fold
  the draco boards onto the shared scored spine`.
- **Gates:** `run_gates.py screamingface-engine --skip-append-only` ALL GREEN
  (ruff check/format, pyright, layering, pytest 2723 passed with coverage ≥80).
  Append-only skip covers exactly the owner-approved import repoints (same
  precedent as OME-1101). E2e: draco-3pass golden byte-identical (100 cases,
  all scored, 0.3593) + seven failure tapes land unchanged + full
  `test_boards.py` replay 4 passed / 2 skipped (boards without fixtures,
  pre-existing).
- **Deviations:** (1) restacked mid-design onto PR #913, which had already
  shipped the scorer parameter + `missing_row_result` hook this plan was about
  to add as a flags dataclass — adopted its board-owned-hook grammar instead;
  (2) `draco_scorer` lives in `grade.py`, not `scoring.py`, honoring
  scoring.py's pinned isolation-from-aggregation invariant; (3) diff ~1.4k
  lines total — over the ticket's ~800 guidance; owner chose one PR anyway;
  (4) review finding (differential old-vs-new run): an error row's Case now
  publishes the selected Case's metadata (e.g. `domain`) where pre-fold
  published `{}` — unpinned by any golden or failure tape (the tapes assert
  stage/code/message only; the golden has zero failed cases). Owner chose to
  KEEP the new behavior (error rows were the only Case shape dropping the
  cases.json extras) rather than restore `{}`: declared in `grade.py`'s
  INVARIANT docstring and pinned by
  `test_draco_failure_integrity.py::test_an_error_row_case_carries_the_selected_cases_own_metadata`.
