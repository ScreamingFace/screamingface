---
ticket: OME-1152
stack: analytics
status: done
started: 2026-09-09
finished: 2026-09-09
---

# OME-1152 — ingestion deadline and decoding review fixes

## Intent

Address the two PR #873 review findings, explicitly authorized by the owner: enforce the approved whole-request deadline and classify corrupt upstream encodings as retryable ambiguity.

## Planned changes

- apps/analytics/src/analytics_service/api.py: single 1.5-second deadline around intake and delivery, preserving cancellation cleanup.
- apps/analytics/src/analytics_service/adapters/posthog.py: bounded retry for HTTPX decoding failures.
- Append regression tests in apps/analytics/tests/test_api.py; correct README deadline description and update the issue mirror.

## Test plan

RED first: slow body plus delivery share the deadline; a stalled upload expires without forwarding; invalid upstream gzip retries with unchanged payload, then either succeeds or returns sanitized 503. Verify admission slots and delivery tasks are released. Run the full analytics gate runner.

## Acceptance

One total request deadline, at most two upstream attempts, immutable retry identity, sanitized retryable decoding failure. Existing tests preserved. Push fixes to the existing PR; leave the issue open for outstanding live acceptance.

## Outcome

- Actual files match the plan; prior tests remain unchanged.
- RED: all four added cases failed as expected (late 202 responses and decoding-related 500 responses).
- Gates: analytics run_gates.py ALL GATES GREEN: append-only tests, lock, lint, format, pyright, 68 tests, 99% coverage, wheel/sdist build. git diff --check passed.
- Wisdom/confidence review: one outer timeout reuses existing cancellation cleanup without changing ports/schema; adapter catches the specific decoding exception only. No dependencies, secrets, persistence or release changes. Existing adapter timeout also protects standalone delivery. Confidence above 95%.
- Commit: fix: bound analytics intake and retry decoding failures (Refs: OME-1152); recorded in git history and PR #873.
- Deviations: none. Live acceptance and rollout remain pending; issue stays open.
