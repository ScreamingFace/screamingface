---
ticket: OME-1165
stack: url4
status: done
started: 2026-09-09
finished: 2026-09-09
---

# OME-1165 — Generic node-scoped structured Log emission

## Intent

Implement the URL4 portion of the approved Log design, merged in PR 876 at 1a53690c. Generic adapters can emit structured observations within a node resolve without acquiring an ExecutionContext. Engine forwarding remains OME-934.

## Planned changes

- packages/url4/src/url4/observe.py: immutable Log attributes and safe scoped sink.
- packages/url4/src/url4/dag/node.py: compatible attributes argument on direct logging.
- packages/url4/src/url4/dag/executor.py: explicit sink binding around resolve.
- packages/url4/tests/unit/test_log_sink.py and test_log_sink_lifecycle.py: new behavioral coverage.
- packages/url4/docs/ observation documentation if the public interface needs an existing reference updated.
- docs/tasks/2026-09-09-OME-1165-structured-log-sink.md.

## Test plan

Write failing tests before production edits. Exercise real DAG execution for attachment, nesting, concurrent scopes, inherited children, expiry and cancellation; verify direct logging compatibility, immutable snapshots, severity and whole-record validation, off-thread rejection, observer failure containment and process-signal propagation. Preserve all existing tests and run the full URL4 gates.

## Acceptance

The package requirements in [the approved spec](../spec/2026-09-09-OME-934-log-seam.md) and steps 2–3 of [the plan](../plan/2026-09-09-OME-934-log-seam.md) pass. No Engine, Client, domain-schema, identity or wire changes. Implementation PR stays draft.

## Outcome

- **Actual files:** Three planned production modules, two new test modules, package README, issue mirror and this ledger.
- **Commits:** feat(url4): add safe node-scoped structured Log emission; Refs: OME-1165.
- **Gates:** RED: both new modules initially failed importing the missing accessor. Additional terminal-ordering regression failed on the error path before the binding was moved inside the resolve try block. GREEN: 45 new tests passed. Full run_gates.py url4 passed append-only, Ruff lint/format, Pyright and the full pytest coverage gate (1,215 collected tests; 98% total coverage, 99% observe.py). No prior tests modified.
- **Deviations:** Public usage documentation added to the existing package README (no package docs directory). No production diagnostics are emitted by the safe sink: silent dropping avoids payload leakage, recursion and throwing log handlers. This implements the approved optional-warning contract. Delivery remains open pending draft PR review and merge.

## Wisdom and confidence review

The interface extends the existing dependency-free observation module and explicit executor binding; no new queue, factory, registry, exporter or domain dependency. Revocation uses shared active state because ContextVar reset cannot revoke a copied child context. The safe path contains Exception only; direct observer failures and BaseException propagation stay intact. Attributes are copied before observation and immutable after publication. The hash excludes the mapping so existing hashable Log construction remains usable. Tests exercise real DAG execution, including nested subtree failure, rather than mocking scheduler internals. Node completion is emitted only after scope exit on both success and failure. Production-size/rate policy belongs to producer schemas, as approved.
