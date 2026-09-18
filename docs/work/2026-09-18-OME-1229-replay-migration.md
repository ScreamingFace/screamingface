---
ticket: OME-1229
status: in_progress
started: 2026-09-18
---
# Case-envelope replay migration

## Intent
Owner approved migrating the stale Client golden expressions in #988. This is the Client fixture sub-issue of OME-887, paired with Engine OME-1228.

## Plan and acceptance
Replay each committed snapshot with the current Engine and original Client candidate spec, with no provider credentials. Compare every original outcome expectation using the existing comparison ladder after substituting only the new expression fingerprint in memory. Write only that fingerprint after the comparison passes. Keep score, statuses, failure map, coverage and snapshots unchanged. Run the unchanged replay test against the migrated fixtures. No Client runtime or harness changes.

## Outcome
Keyless replay passed for DRACO-3pass (100 cases, 0.3593), IFEval (50, 0.9184), HealthBench-worst30 (157, -0.091), GDPval-text (25, 0.8044). All original statuses, failure maps, coverage and scores matched. Only four expression hashes changed; snapshots and outcome expectations are untouched. Atomic fixture migration shares the OME-1228 worktree/PR to keep contract and fixtures aligned. Unmodified replay tests: 4 passed; 2 unrelated boards lack fixtures and skip as before. Full Client gates green (lint, format, types, tests/95% coverage threshold, notebooks, build and distribution).
