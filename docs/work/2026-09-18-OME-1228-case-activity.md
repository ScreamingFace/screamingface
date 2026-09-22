---
ticket: OME-1228
status: in_progress
started: 2026-09-18
---
# Case attribution

## Intent
Owner authorized a separate issue and draft PR landing before #980. Implement authoritative case metadata without changing model inputs.

## Planned changes
Benchmark candidate request envelope and scoped metadata, shared builders/call sites, activity adapter, tests. No URL4 or Client changes.

## Test plan
Actual URL4 requests and candidate-handler decoding, plain/structured input equivalence, concurrent tasks/nested runs, context reset, privacy/off behavior. Full Engine gates.

## Acceptance
Case IDs on existing model-call records, unchanged prompts/results, no inferred identities or cross-case leakage. Draft stays In Progress.

## Outcome
Implemented explicit case-v1 request envelopes in all five benchmark candidate builders, run-bound benchmark Case scope, and safe plugin-owned model-log attribution. No execution-core dependency on activity; no URL4 or Client changes. Input equivalence was verified through actual URL4 execution for text and structured MedXpertQA inputs, including quotes/newlines/literal dollar text. A fake-model end-to-end run verified prompts exclude metadata while start/completion records include Case identity.

16 new tests pass; existing candidate-foundation tests pass. Full Engine gates green: lint, format, Pyright, layering and full pytest with 93%+ coverage (required 80%). No paid provider calls. Self-review: small explicit envelope avoids ambiguous JSON sniffing; metadata cannot affect grading/auth; unsafe telemetry IDs omit only that field; tokens reset on failures/cancellation and child runs cannot inherit a parent's identity.

Deviation: the authorized request-contract change necessarily changes three existing URL4 SHA256 snapshots. Repinned only expected hashes and preserved the byte-for-byte assertion; no behavioral assertions removed. Used the runner's append-only exception for that snapshot migration; all other gates remain enforced. PR remains draft and issue In Progress. Stage/grading attribution and Client presentation remain follow-ups.

## Review follow-up — planned
Owner approved the review fixes. Add case identity once in the shared Inspect candidate builder and verify actual model activity through an imported board. Define activity-to-result joins as string comparison (integer 42 matches "42"; "007" remains distinct), with transport coverage. Migrate only the four Client expression fingerprints after keyless replay verifies unchanged cached requests, statuses, failure codes, coverage and scores. Keep the PR draft. Existing assertions and score expectations remain intact.

Review fixes: shared Inspect builder now supplies Case identity; its real imported-board activity test failed before the fix and passes afterward. Integer/leading-zero transport coverage documents string-based joins. All 32 focused tests pass. The Client fixture migration is tracked in OME-1229. A concurrent replay environment sync removed optional Inspect modules during the first full gate; sequential rerun with the Inspect extra installed passed all Engine gates. Full Client gates and unchanged keyless replays also pass. Review: no benchmark-specific logging implementation, no outcome/snapshot changes, no new dependencies; final PR stays below 500 changed lines.


## Selected-case numbering — 2026-09-18

Intent: owner approved selected-case ordinals in #988, forwarding in #980 and UI in #983. Model roles remain deferred.
Planned: shared selection annotation, optional envelope position/count, scoped transport, regression tests and replay migration.
Acceptance: selected order determines numbering; inputs and scores unchanged; no arrival-order inference.
Status: in progress.

Numbering progress: 16 new selection/envelope/scope tests pass; actual URL4 preserves input for two concurrent candidates with identical selected positions. Full Engine gates found existing protocol setup/snapshot migrations; registry installation failure fixed (18 focused tests pass). Waiting for explicit prior-test migration confirmation per sdlc-python before changing those tests and replay fingerprints. No Engine numbering commit/push yet.

Owner explicitly resumed and requested finishing numbering. Migrating protocol setup/snapshots and Client replay expression fingerprints as required by that approved change; preserve all outcome, order, concurrency and score assertions.

Numbering Engine validation: 70 focused checks and all Engine gates passed (lint, format, types, layering, full tests/coverage). Existing protocol tests now install the shared selection route and assert the requested prefix count instead of the retired slice syntax; byte snapshots repinned. New tests prove unchanged input and independent concurrent-candidate positions. Wisdom review: metadata stays outside model inputs, shared protocol owns selection order, no execution-core/activity dependency and no unbounded identity map. Cached benchmark replay migration continues under OME-1229 before final delivery. Owner's request to finish includes the necessary existing-test migration; the gate runner's append-only exception is limited to that migration.

## Review and main integration — 2026-09-22
Owner requested review of #988 and conflict resolution. Review fixed head 7199cae0 against main 673c5343, then merge current main preserving the stacked #980 ancestry. Preserve both benchmark abstraction updates and case metadata semantics. Run Engine and affected Client/replay checks; resolve confirmed review findings before updating the PR. No merge to main or ticket closure requested.

Outcome: main integrated cleanly with merge commit 469ecdd1; no manual conflict hunks. Standards and spec reviews found no actionable issues in the original diff. Integration found the newly shipped ContractEval builder missing the envelope metadata, so it now passes Case ID and selected position/count. The new full-evaluation regression failed before wiring and passes afterward; the follow-up spec review found no remaining issue. Owner explicitly approved migrating ContractEval's old slice assertions to the shared selector with the same limits (5 and 50).

Full Engine and Client gates pass, including coverage, notebook validation and distribution checks. Unmodified recorded replay tests pass for all four available boards (382 cases): DRACO-3pass, IFEval, HealthBench-worst30 and GDPval-text. Expression fingerprints, scores, statuses, failure codes and coverage all match their existing goldens. Three other boards explicitly skip because no recorded fixtures exist; ContractEval is covered by its fake-model full-evaluation tests. No paid model calls or further fixture changes. The gate runner's append-only exception covers only the approved existing-test migrations. Review status remains open; tickets remain unclosed pending merge.
