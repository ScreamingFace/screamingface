---
ticket: OME-887
stack: repo
status: done
started: 2026-09-10
finished: 2026-09-10
---

# OME-887 — Refine long-running evaluation activity

## Intent

Record owner-approved refinements to the proposed activity design: recoverable rolling limits, bounded priority and summaries, honest reconnect behavior, a fixed 60-second heartbeat following the owner's correction, and explicitly ephemeral activity with no new server-side archive. This updates documentation, not product implementation.

## Planned changes

- Update the activity spec and plan.
- Update the existing task mirror and PR description.

## Test plan

Check document consistency, relative links and diff hygiene. Specify pressure, recovery, simulated multi-day and reconnect acceptance tests for implementation. No runtime tests for this documentation-only change.

## Acceptance

Limits never become a lifetime logging cutoff or block evaluation work. Priority and summaries remain bounded. Heartbeats stay at 60 seconds while eligible async work is active; elapsed timers do not fabricate observations. Missing replay is disclosed; durable export is not requested work.

## Outcome

- **Actual files:** spec, plan, task mirror and this ledger; PR description updated to match.
- **Commits:** docs: clarify ephemeral activity limits and fixed heartbeats; Refs: OME-887.
- **Gates:** independent Standards and Spec reviews; clarified fresh evidence before restarting an elapsed timer after reconnect. Relative links and diff hygiene checked. No product code or runtime tests changed.
- **Deviations:** owner superseded the earlier heartbeat-backoff direction with fixed 60 seconds and explicitly rejected new server-side history storage. Remaining contract decisions and implementation approval are unchanged.
