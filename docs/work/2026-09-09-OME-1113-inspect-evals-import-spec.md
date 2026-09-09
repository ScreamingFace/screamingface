---
ticket: OME-1113
stack: repo
status: in_progress
started: 2026-09-09
finished:
---

# OME-1113 — Write the spec for importing inspect_evals benchmarks

## Intent

The inspect_evals import architecture was decided 2026-09-04 but lives in decision
comments (`OME-1097` / `OME-1103`) and a local architect doc. This unit turns it into one
`docs/spec/` artifact that the two build tickets (`OME-1115` adapter plugin, `OME-1116`
importer) execute directly — package boundary, shim contract, judge routing, revision
identity formula, grading-route-as-check-surface — consuming the merged `grade_case` seam
and the envelope decisions, never redefining them.

## Planned changes

- `docs/spec/2026-09-09-OME-1113-inspect-evals-import.md` — the spec (new)
- `docs/tasks/2026-09-09-OME-1113-inspect-evals-import-spec.md` — issue mirror (new;
  none existed)

## Test plan

- No code; the "tests" are the spec's own acceptance hooks: every contract statement
  points at a real symbol (`spine/scored.py` `GradeRequest`/`CaseGradeOutcome`/`GradeCase`,
  `definition.py` `Benchmark`/`CheckSurface`/`BenchmarkDeclaration`, `deployment.py`
  registrations) verified present on `main` at write time.

## Acceptance

- Spec covers both build tickets with zero re-derivation needed: plugin package layout +
  dependency carriage + registry wiring; the TaskState shim contract; judge routing;
  revision identity; dataset snapshot + license check; numeric acceptance bars.
- Consistent with `grade_case` (`OME-1097`, merged) and the envelope decisions
  (`OME-1103` 2026-09-04 comment) — consumes, never redefines.
- Owner review before commit/PR (explicitly requested: no commit, no push until manual
  review).

## Outcome (fill at the end — required before COMMIT)

- **Actual files:**
- **Commits:**
- **Gates:**
- **Deviations:**
