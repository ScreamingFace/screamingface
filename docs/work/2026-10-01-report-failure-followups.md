---
ticket: OME-1448
stack: screamingface
status: complete
started: 2026-10-01
finished: 2026-10-01
---

# Report failure-path follow-ups

## Intent

Address the four concrete findings supplied after reviewing 6ebc8614: stale transport membership, loss of healthy siblings on indexing failure, inert download retry after replacement, and relative runtime artifact-directory status.

## Planned changes

Use identity-safe prepared-result associations and release them on failed/cancelled runs. Settle final decoding per candidate using the existing partial-report contract. Track successful browser export preparation independently from snapshot existence. Record an absolute serving artifact path.

## Test plan

Reproduce each finding before implementation with append-only regressions. Cover both transports, both evaluation runners, sync/async browser export retries, and serving/status from different working directories. Run all screamingface gates against 6ebc8614 and independent standards/spec reviews.

## Acceptance

Failed evaluations cannot misassociate subsequent standalone results; final indexing errors name failed candidates and preserve healthy partial reports; download retries after a durability error succeed; status reports the serving directory and bytes from any working directory. Existing APIs/wire formats and prior tests stay unchanged.

## Outcome

All four supplied findings were reproduced and fixed. The initial regressions failed for stale membership, lost healthy partials, inert retry and relative runtime status. Independent review also reproduced cancellation leaving an unscheduled candidate; evaluation-scoped final cleanup fixes that without discarding unrelated prepared membership.

- 17 new regression cases pass across both transports, both runners, sync/async download retry, all-decoding-failed, and cancellation beyond the concurrency limit.
- 66 focused tests passed before the additional cleanup regression; the final complete SDK gate run passed against 6ebc8614.
- All gates green: append-only preservation, Ruff lint/format, Pyright, parallel full pytest with 95% coverage threshold, notebook validation, build and distribution validation.
- Independent standards and spec reviewers found no remaining actionable issue after scoped cleanup. Existing tests were unchanged.
- Wisdom review: reuse the established partial-error assembly, isolate each lifecycle boundary, retain actual object identity, and keep the export readiness flag independent of optional files. No new dependency, wire/public format change or secret handling change. Scope stays in the SDK.
- Continue the user-authorized push to PR #1156. No review comments, paid evaluations or new tickets.

