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
