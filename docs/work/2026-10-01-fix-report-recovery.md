---
ticket: OME-1448
stack: screamingface
status: complete
started: 2026-10-01
finished: 2026-10-01
---

# fix-report-recovery — isolate damaged membership and overlapping presentation

## Intent

Fix the two remaining review follow-ups authorized by the user: malformed saved evaluation metadata must not poison healthy report recovery, and an overlapping render must not clear a pending export marker.

## Planned changes

- Validate evaluation membership when loading manifests, retaining discovery-only legacy metadata and translating invalid recovery context to the existing metadata error.
- Track active render/export operations per evaluation under a process-local lock; retain the existing best-effort marker format and release bookkeeping on handled failures.
- Add append-only regression tests, plus a short spec/plan record.

## Test plan

First reproduce valid-JSON damaged siblings and unrelated membership, then reproduce both render/export overlap orders and concurrent exports using real lifecycle boundaries. Verify partial reports, exact SDK errors, pending interruption discovery and eventual ready state. Run all screamingface card gates against ab48b155.

## Acceptance

Healthy saved results remain recoverable when another membership record is damaged. No presentation operation clears another active operation's pending marker. Existing public APIs, stored/exported result formats, existing tests and paid-call behavior remain unchanged.

## Outcome

Implemented both fixes and preserved legacy discovery-only metadata. All lifecycle writers, including recovery copies, now preserve active render/export markers under one lock.

- RED: the initial 14 parametrized regression cases failed for the reviewed bugs. The recovery-copy follow-up was also reproduced before its fix.
- GREEN: 16 new regression cases pass; robustness plus existing recovery-notice tests total 39 passed.
- All screamingface card gates pass against ab48b155: append-only tests, Ruff lint/format, Pyright, full pytest with the 95% coverage threshold, notebook validation, build and distribution verification.
- Independent standards and spec reviews found no remaining actionable issues after the recovery-copy correction. Existing tests were unchanged.
- No paid evaluations or new tickets. Initially prepared as a local conventional commit and applicable patch.
- The user subsequently authorized pushing to PR #1156. Rebased onto its newer head 76c7c827 without conflicts; all screamingface gates passed again against that base before push.
