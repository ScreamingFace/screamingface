---
ticket: OME-1475
stack: screamingface-engine
status: done
started: 2026-10-06
finished: 2026-10-07
---

# ome-1475-musique-spec — spec and plan for the hand-built MuSiQue Benchmark (PR 1)

## Intent

MuSiQue is one of the ten Benchmarks product asked for in Q4 2026 (`OME-1457`), and the first
of the three hand-built ones. It is not in inspect_evals, so it is built the way `medxpert` was:
Case Preparation, grading one answer, aggregating the score. This unit writes the spec and the
plan that the code PRs follow. It branches from main after #1236 (provenance) and the OME-1268
stack (Named Scores) merged, so the Benchmark declares its provenance and reports three scores
from day one.

## Planned changes

- `docs/spec/2026-10-07-OME-1475-musique-ans.md` (new)
- `docs/plan/2026-10-07-OME-1475-musique-ans.md` (new)
- `docs/tasks/2026-10-07-OME-1475-musique-ans.md` (new mirror)

## Test plan

- Docs only; no code. The spec names the tests the code PR writes first.

## Acceptance

- Owner approved the design in conversation on 2026-10-07 (all 17 decisions) and asked for all
  four PRs in one pass; spec and plan land here as the record.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned.
- **Commits:** one docs commit on `OME-1475-pr1-musique-spec`.
- **Gates:** docs only; both spec diagrams and the plan's code map rendered with `mmdc` and read.
- **Deviations:** the stack branches from main, not from #1236, because #1236 and the OME-1268
  stack merged before code started. Support F1 joined the scores after Named Scores landed.
