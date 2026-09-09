---
id: OME-1165
linear_url: https://linear.app/openmined/issue/OME-1165
status: Backlog
priority: High
labels: [url4-python-sdk, agentic, autonomous]
created: 2026-09-09
closed:
---

# Add a generic node-scoped structured Log sink to URL4

Owner: Keelan Jordan. Milestone: Public Launch.

## Approved design
Owner approved the revised design on 9 September 2026 in docs-only draft [PR #876](https://github.com/ScreamingFace/screamingface/pull/876). Canonical contract: docs/spec/2026-09-09-OME-934-log-seam.md; plan: docs/plan/2026-09-09-OME-934-log-seam.md. Implementation starts after the docs merge, in a separate package worktree and draft PR.

## Scope
Extend packages/url4 observation Logs with optional immutable flat scalar attributes and a generic node-scoped LogSink/current_log_sink accessor. Extend ExecutionContext.log compatibly and bind an explicit safe callable alongside existing node sinks. No Engine, Benchmark, Gateway, schema or exporter dependencies.

## Acceptance
* Existing three-argument Log construction and direct observer/log failure behavior remain compatible.
* A sink belongs to the node resolve that bound it. Child tasks inherit it while active. Observed nested execution binds its own sink and restores the outer; unobserved nested execution inherits an active outer and creates no new span.
* Finally-based expiry on success, error and cancellation revokes copied child contexts: fresh accessors return None; retained callables silently drop. Concurrent scopes remain isolated; off-thread submissions drop.
* Synchronous non-blocking emission creates no tasks or I/O. Ordinary validation/submission/observer failures are contained; cancellation and process signals are not swallowed. Bounded diagnostics contain no payload or raw exception text.
* Whole-record validation accepts nonempty exact string bodies, string keys, exact builtin scalar values and finite floats; no coercion. Severity strips whitespace and uppercases, accepting exactly DEBUG, INFO, WARN, ERROR; reject aliases and nonstrings.
* Defensive immutable attribute snapshots resist mutation through caller mappings and observations.
* Formal tests cover compatibility, no-observer behavior, import isolation, concurrent/nested/child scopes, expiry, threading, cancellation, original-error preservation, validation and mutation. Full URL4 gates pass.

## Delivery boundaries
OME-934 owns Engine forwarding and safe bridge buffering and depends on this issue. OME-1161 owns production activity records and concrete serialized size/rate limits; OME-932 owns evaluation lifecycle, typed terminal observations and scoring. This package interface supplies emission only. No new wire event, URL grammar or identity change; saved failure diagnostics remain separate. Keep implementation PR draft until the owner requests readiness.
