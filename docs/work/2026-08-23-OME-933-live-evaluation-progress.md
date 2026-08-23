---
ticket: OME-933
stack: screamingface
status: in_progress
started: 2026-08-23
finished:
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
- `packages/screamingface/src/screamingface/_ui/evaluation_state.py`
- `packages/screamingface/src/screamingface/_ui/evaluation_view.py`
- `packages/screamingface/tests/test_evaluation_progress_panel.py`
- Additional Client tests only if a contract boundary is not owned by the existing progress suite.

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

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** pending.
- **Commits:** pending.
- **Gates:** pending.
- **Deviations:** pending.
