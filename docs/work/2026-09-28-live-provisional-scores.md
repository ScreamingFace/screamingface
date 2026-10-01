---
ticket: OME-932
stack: screamingface-engine + screamingface
status: done
started: 2026-09-28
finished: 2026-09-28
---
# Live provisional scores

## Intent
Complete the notebook-visible IFEval preview: publish cumulative canonical scores after each grade and display them until the final result arrives. User explicitly approved Engine + Client wiring. Client ticket assignment is deferred to PR filing; no new ticket without confirmation.

## Plan and acceptance
Use an optional execution observation callback carrying board identity, canonical CaseResult and the existing board scorer. Activity observer owns only cumulative progress state, never grading. Emit scalar-only versioned snapshots, no inputs/answers/evidence. Deduplicate cases, coalesce fast updates, isolate observer failure. Client validates finite scores/counts/revisions and displays the numeric running score until authoritative result overrides. Add tests before implementation including a blocked second case. Run both stack gates and restart preview after verification.

## Verification so far
- Five new Engine tests pass: real URL4 early score before case 2 completes, deduplication/privacy, observer isolation, cumulative recovery after coalescing, disabled/closed observers.
- Twelve new Client tests pass, including the real notebook widget Score cell, zero, invalid/stale/foreign snapshots, candidate isolation, no gradeable cases, and final-result precedence.
- Real HTTP/WebSocket cached replay: 22 snapshots reached the Client decoder, beginning at one graded case; all 50-case outcomes/failures/coverage and final score 0.9184 unchanged. No paid calls.
- Engine full suite: 4044 passed; one existing stage-only test assumes every Log has activity keys. Permission requested to filter by activity schema while retaining all parity assertions. No prior tests changed in this iteration.
- Local stack and preview kernel refreshed; IFEval preview now consumes live provisional scores. Changes remain uncommitted pending that required test migration.
- Full Client gates are green: lint, formatting, types, full tests/coverage, notebook checks, build and distribution. Additional widget/identity tests added during the gate run passed separately; final Client type check is clean.

## User-directed display simplification
User explicitly requested removal of the provisional/graded-count text during live scoring. Keep the running score and final-result precedence; migrate the new display assertions to require no provisional label.

## Approved continuation
The user approved existing test migrations and removal of the provisional label. All-board implementation and final verification are tracked in `2026-09-28-all-benchmark-live-scores.md`. The earlier pending-migration notes above describe intermediate verification, not the final state.

## Verified outcome
Engine and Client gate runners both passed (lint, format, types, full tests/coverage; Engine layering; Client notebook generation, build and distribution). Implementation complete and reviewed; draft publication/ticket linkage tracked separately. Planned commit: `feat: publish live scores across shipped benchmarks`. No paid calls or merge.
