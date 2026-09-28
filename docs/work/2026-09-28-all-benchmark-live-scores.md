---
ticket: OME-932
stack: screamingface-engine
status: done
started: 2026-09-28
finished: 2026-09-28
---
# All-benchmark live scores

## Intent
Extend the approved IFEval running-score preview to every shipped benchmark. Keep scoring semantics in each board and keep final results authoritative.

## Planned changes
- Shared scored-path completed-grade publication for every aggregate consumer, including imported async judges.
- Generalize the early typed-grade transport for built-ins so case one can update while case two is answering; final aggregation must consume grades without repeating grading.
- Registry-driven tests, benchmark protocol/replay migrations, and authoring guidance.

## Test plan
First prove actual generated built-in routes emit snapshots matching canonical final scores with activity enabled, without changing requests or final results. Prove async grading emits before a blocked later judge. Then prove early timing for every built-in and test failure/retry/order semantics. Preserve prompt, score, call count and accounting parity during fixture migrations.

## Acceptance
All shipped boards update the existing numeric Score column when canonical grades become available. No client-specific benchmark formulas or additional grader calls. Built-in updates must not wait for final aggregation. All gates and replay parity pass before push.

## Outcome
Implementation complete; final Client gate run and draft publication pending. Existing-test migrations explicitly approved by the user.

## Verified first slice
- Shared async aggregate consumption now publishes each canonical CaseResult through the existing optional progress port.
- New blocked-second-grade test proves the first score is emitted before later grading completes, with one grade invocation per case.
- A real imported GSM8K aggregate route emits the first-case score 1.0 and retains the authoritative two-case result 0.5 through URL4 Log transport.
- Nine focused tests passed with the Inspect extra installed, including existing imported aggregation activity coverage. Twelve core incremental/progress tests passed separately.
- Initial generated-route matrix confirmed the seven remaining built-ins cannot gain early score delivery from this callback alone: their synchronous final aggregation crosses a worker boundary, and occurs after all answering. Those migrations remain outstanding, not claimed complete.
- Snapshot/replay/schema-filter migrations were subsequently approved; fixture builders remain outside active observation to avoid manufacturing extra progress.

## Approved migration and implementation
The user explicitly approved existing fixture and schema-filter migrations. All eight built-in protocols now carry canonical early grades into final aggregation. Shared scoring bindings preserve board formulas and selected indexes; immutable selection loading is bounded to one cached selection per early endpoint. Sixteen generated-protocol timing checks (eight boards × solo/fusion) pass with case two blocked. Full Engine unit suite reached 4480 passing with one old raw-route test; that test has now been migrated through the real early endpoint, retaining score/evidence/cost assertions, and passes. Recorded replay and final gates remain in progress.

## Final verification and wisdom review
- Engine gate runner: lint, format, types, layering, full tests and coverage all green. The append-only exception applies only to the user-approved migrations.
- Recorded cache-only replay: DRACO-3pass 100 cases / 0.3593; HealthBench-worst30 157 cases / -0.091; GDPval-text 25 cases / 0.8044. Final scores, statuses, failures and coverage unchanged; only revision/expression fingerprints migrated. IFEval's prior 50-case replay remained 0.9184.
- Seven transport/binding tests verify no regrading, original selected positions, anonymous failure parity, and corrupt/foreign-grade rejection.
- Wisdom: shared binding reuses each board's canonical hooks and scorer; no Client formulas, no URL4 SDK change, and no model calls added. Scalar snapshots contain no prompt/output/evidence. Final CandidateResult remains authoritative. Imported grading remains at its existing aggregation phase.
- Protocol revisions deliberately change for early execution; the old raw Python aggregation helpers remain parity oracles.

## Verified outcome
Engine and Client gate runners both passed (lint, format, types, full tests/coverage; Engine layering; Client notebook generation, build and distribution). Implementation complete and reviewed; draft publication/ticket linkage tracked separately. Planned commit: `feat: publish live scores across shipped benchmarks`. No paid calls or merge.
