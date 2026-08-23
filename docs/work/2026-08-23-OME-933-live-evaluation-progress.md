---
ticket: OME-933
stack: screamingface
status: done
started: 2026-08-23
finished: 2026-08-23
---

# OME-933 — redesign live Evaluation progress

## Intent

Replace the aggregate notebook progress panel with a truthful, always-alive per-Candidate table.
Use the existing typed Event stream for activity, cost, cache, lifecycle, and exact terminal Case
counts; keep final Candidate Results authoritative for scores and outcome classification.

## Planned changes

- `docs/tasks/2026-08-21-OME-933-live-evaluation-progress.md`
- `docs/spec/2026-08-23-OME-933-live-evaluation-progress.md`
- `docs/plan/2026-08-23-OME-933-live-evaluation-progress.md`
- `docs/work/2026-08-23-OME-933-live-evaluation-progress.md`
- `packages/screamingface/src/screamingface/_evaluation/runner.py`
- `packages/screamingface/src/screamingface/_evaluation/progress.py`
- `packages/screamingface/src/screamingface/_evaluation/url4.py`
- `packages/screamingface/src/screamingface/_ui/evaluation_state.py`
- `packages/screamingface/src/screamingface/_ui/evaluation_view.py`
- `packages/screamingface/tests/test_live_candidate_progress.py`
- `packages/screamingface/tests/test_evaluation_progress_panel.py`
- `packages/screamingface/tests/test_progress.py`
- `packages/screamingface/tests/test_check_disclosure_display.py`

## Test plan

- RED first for Candidate-scoped event routing and exact terminal Case span counting.
- RED first for 10 Candidates × 100 Cases, concurrent out-of-order completion, replay-safe folding,
  terminal failures, and final-result reconciliation.
- RED first for SFDS table structure, horizontal overflow, keyboard access, reduced motion, and
  light/dark token use.
- Preserve existing Event callbacks, final Reports, cache provenance, cost accounting, notebook
  distribution, and all prior progress tests.

## Acceptance

- Every Candidate has one stable row in input order with truthful Status, Progress, Score, Cost,
  and Cache evidence.
- Progress counts only `(operation="RelUrlNode", name="/benchmarks/case-execution")` terminal spans
  and uses the Evaluation's selected Case count as its denominator.
- Existing Events keep running rows alive; the UI never fabricates phases, delays, values, or Case
  identities.
- Scores appear only from successfully decoded final Candidate Results.
- The app-register SFDS v2 surface remains accessible, readable in light and dark, and horizontally
  scrollable at narrow widths.
- The full `screamingface` quality gate passes.

## Outcome

- **Actual files:** the spec/task mirror and every production/test file listed above.
- **Commits:** `f718b42b` (approved spec/plan), `aa7d3282` (Candidate-scoped implementation).
- **Gates:** 77 focused progress/evaluation tests passed; 1,043 package tests passed with one
  skip before the final edge-case additions; the complete official `screamingface` gate then
  passed Ruff, Pyright, ≥95% coverage, notebook validation, build, and distribution checks.
- **Deviations:** opaque URL4 replay cannot know its selected denominator before result decoding,
  so it truthfully renders the exact observed numerator until the final Report supplies the total.
  The approved plan intentionally replaced aggregate-panel assertions with Candidate-table
  assertions; the append-only detector was skipped only for that recorded contract replacement,
  while every retained and new test still ran in the full gate.
