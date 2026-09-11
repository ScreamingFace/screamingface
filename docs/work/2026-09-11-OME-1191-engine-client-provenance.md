---
ticket: OME-1191
stack: screamingface-engine
status: in_progress
started: 2026-09-11
finished:
---

# OME-1191 — Engine Client-version provenance design

## Intent

Implement the Engine follow-up to OME-416. The owner chose the existing run-history
lifetime, not a new durable record. User approved implementation and draft PR creation.

## Planned changes

- Design spec and task mirror in this isolated worktree.
- Engine-only capture, scheduling propagation, and ephemeral evidence implementation.

## Test plan

- Parser tests cover valid releases/local suffixes and absent/invalid/oversized input.
- Adapter tests cover run isolation, rejected starts, queue handoff, and cleanup.
- Verify existing Client decoding before choosing a returned evidence representation.

## Acceptance

- Retention follows each backend's existing lifecycle; no new persistent store.
- Compatibility and retrieval limits are explicit before implementation approval.

## Outcome

- Actual files: new Engine `client_provenance.py`; REST, scheduling port, local/queue
  adapters, queue codec, worker environment, Runner parameters and lifecycle wiring;
  two new test modules; four test-double signatures; spec, plan, mirror, ledger.
- RED: parser tests initially failed on the absent module; wiring tests then exposed
  missing REST/local evidence and missing queue version propagation.
- Focused validation: 126 tests passed before final signature-only approval.
- Full suite: 2831 passed, 9 skipped, coverage 93.23% (80% required) before the final
  optional test-double signature addition. The final complete gate runner reports
  ALL GATES GREEN, including lint, format, pyright, layering, full tests and coverage.
- Verified actual Engine Started/Log frames decode through the merged Client `_RunState`.
- Retention audit: ordinary lifecycle sequencing and stream storage; no new database,
  no Python log emission, no summary fields; SpanRelay ignores Log events.
- Approved deviation: owner explicitly approved four optional `client_version` argument
  additions to existing test doubles. Exact text comparison verifies there are no other
  changes in those four files. The append-only checker cannot represent this exception;
  use `run_gates.py screamingface-engine --skip-append-only` for this approved unit.
- Wisdom: one bounded parser and one Executor decorator; no shared URL4 schema changes,
  no base Client change, no raw-header retention, and no altered authentication or cache
  behavior. Per-run context never inherits the worker's ambient Client version.
- Commit: `feat(engine): retain Client version in ephemeral run evidence`;
  Refs: OME-1191. Draft only; issue stays open for review and merge.
- Logs: `.docs/OME-1191-focused.log`, `.docs/OME-1191-full-tests.log`,
  `.docs/OME-1191-gates-approved.log` (local).
