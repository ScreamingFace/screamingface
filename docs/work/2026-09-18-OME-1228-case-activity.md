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
