---
ticket: OME-1113
stack: repo
status: done
started: 2026-09-09
finished: 2026-09-10
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

- **Actual files:** as planned — the spec, this ledger, the `docs/tasks/` mirror.
- **Commits:** `0ff077a7` docs(spec): specify importing inspect_evals benchmarks;
  `51aafe7a` docs(spec): sharpen inspect import framing + upstream-export nice-to-have
  (owner's review edits); merged via PR #869 (`e409b5b7`).
- **Gates:** none applicable — docs-only change; pre-commit hooks green.
- **Deviations:** owner review sharpened the framing before merge (live catalogue count,
  attribution note, upstream-export nice-to-have); mirror + ledger close landed in a
  follow-up docs PR because the review edits merged ahead of the close-out.
