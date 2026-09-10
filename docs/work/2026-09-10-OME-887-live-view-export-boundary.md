---
ticket: OME-887
stack: repo
status: done
started: 2026-09-10
finished: 2026-09-10
---

# OME-887 — Clarify live activity versus durable export

## Intent

Record the owner-requested boundary in PR #885: the Logs tab is a bounded live view; durable run-log export requires separate delivery work. This clarification does not authorize product implementation or change existing retention settings.

## Planned changes

- Clarify the spec's live-view, transport-retention and archive boundaries.
- Align the Client delivery plan and task mirror.

## Test plan

Review the documentation diff and relative links; run git diff --check. No runtime tests for documentation-only changes.

## Acceptance

The proposal makes no complete-archive promise from notebook history or temporary transport, and explicitly separates durable export and its retention/loss contract.

## Outcome

- **Actual files:** spec, plan, task mirror and this ledger.
- **Commits:** docs: clarify live activity and durable export boundary; Refs: OME-887.
- **Gates:** documentation diff and relative ledger link reviewed; git diff --check passed. Runtime tests not applicable.
- **Deviations:** none. OME-887 remains open; implementation approval and other proposed design decisions are unchanged.
