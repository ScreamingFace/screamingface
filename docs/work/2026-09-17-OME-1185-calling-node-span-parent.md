---
ticket: OME-1185
stack: screamingface-engine
status: done
started: 2026-09-17
finished: 2026-09-17
---

# OME-1185 — Send the calling node's span id to aigateway, not the run's root

## Intent

Outbound aigateway calls carry `traceparent: 00-<trace_id>-<root_span_id>-01`, so every
gateway server span attaches to the RUN, not to the node that made the call. The trace is
connected but flat: verified in production on 2026-09-17
(trace `e2f0bfb83234b51d0228ce0fa39c0334`: 200 spans, engine 176 + aigateway 24, 1 root, 0
orphans, and all 24 gateway server spans share the single parent `c84b53aff1cdcb16`). You can
see a run made eleven provider calls; you cannot see WHICH node made the slow one.

`OME-1119` chose `root_span_id` deliberately, because nothing emitted a root span yet and a
per-node parent would have dangled. `OME-1130` removed that premise: the runner now emits one
`SpanEvent` per node AND a synthetic root, so both ids exist in the exported trace.

## Design decisions

**D1 — where the node's span id comes from.** url4 threads the current span as a VALUE on
`ExecutionContext` (`with_span`), not as a ContextVar, and `url4.observe` exposes sinks
(`current_usage_sink`, `current_response_sink`, `current_log_sink`) but no current-span
accessor. Two ways to reach it from `runner/connector.py`:

- (a) add `current_span_id()` to `url4.observe`, bound alongside the sinks in
  `_bind_node_sinks`; or
- (b) bind it engine-side, in `Url4Executor._Bridge.on_event`, off the `NodeStarted` event.

Chosen: **(b)**. `Observer.on_event` is called SYNCHRONOUSLY and inline by `Executor._eval`,
from the node's own `asyncio.Task`, immediately before `node.resolve` is awaited — the exact
context every outbound call of that node then runs in, and the same per-Task isolation
`_bind_node_sinks` documents for the sinks. So (b) reaches the same value at the same moment
with no new url4 surface. (a) would also be correct, but it widens a published package API and
makes this a two-package change (`D9` cross-cutting: epic + sub-issue per package) for a
ticket labelled `screamingface-engine` alone. If a second embedder ever needs the current
span id without an observer, promote this to (a) then.

**D2 — the ordering question the ticket asks to settle (ACCEPTED, with reasoning).** A node's
`SpanEvent` is published on FINISH (`_RunState._finish`), while the outbound call happens
mid-node, so the gateway's `parent_span_id` names a span that is exported later. This is
acceptable:

1. OTLP is explicitly order-free: a backend assembles a trace from spans arriving in any
   order, and a parent arriving after its child is the normal case for any instrumented
   server call (the client span always closes after the server span it caused).
2. The only lossy case is a run killed mid-node: the gateway span's parent never arrives. But
   `OME-1130` already refuses to export an unfinished span, so that node's span is missing
   from the trace EITHER WAY — the choice is between a gateway span orphaned under a missing
   node and a gateway span misattributed to the root. An orphan states the truth ("the node
   that made this call never finished"); attaching it to the root states a falsehood that
   renders as a correct-looking trace, which is worse, because it is not diagnosable.
3. The killed-run case is already visible from the run's own `Terminated(stopped|failed)`
   frame, so an operator is not left guessing why a parent is missing.

No change is made to when spans are exported.

**D3 — fallback stays the root.** Outside any node (run-level calls, a scope bound with no
observer attached) `current_traceparent()` still renders `root_span_id`. That is not a
fallback for convenience: outside a node the run's root IS the current span, so this is the
correct answer, and it keeps every `OME-1119` assertion true.

**D4 — no reset on node finish.** The binding is set, never reset. A ContextVar token created
in one Task and reset in another raises `ValueError: Token was created in a different
Context` — the defect `test_a_cancelled_run_does_not_raise_from_the_trace_scope` pins. Each
node's binding dies with its own Task, so there is nothing to clean up; `run_trace_scope`
clears the node span on entry so a nested or subsequent run can never inherit a stale one.

## Planned changes

- `apps/screamingface-engine/src/screamingface_engine/trace_scope.py` — a second ContextVar
  for the calling node's span id, `bind_node_span()`, and `current_traceparent()` preferring
  it over the root; `run_trace_scope` clears it on entry.
- `apps/screamingface-engine/src/screamingface_engine/runner/executor.py` — `_Bridge.on_event`
  binds `NodeStarted.span_id` before any queueing policy runs.
- `apps/screamingface-engine/tests/unit/test_traceparent_propagation.py` — appended section.

## Test plan (RED first)

- A node span bound inside a run scope renders as the traceparent's SPAN segment, with the
  trace id unchanged.
- With no node bound, the scope still renders the run's root — `OME-1119`'s contract.
- A nested `run_trace_scope` does not inherit the outer scope's node span.
- End to end through `Url4Executor`: the span id aigateway receives is one of the node span
  ids the run actually exported (walked off `Traced.span.span_id`, never `repr()`), and is NOT
  the run's `root_span_id`. This is the flatness the ticket names, asserted directly.
- Binding outside any run still sends no header (absent stays absent).

## Acceptance

- The gateway's traceparent names the calling node's span, not the run's root.
- Every prior test in the file stays green, unmodified.
- `uv run .claude/scripts/run_gates.py screamingface-engine` all green.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** exactly as planned — `trace_scope.py`, `runner/executor.py`
  (`_Bridge.on_event`), and an appended section in
  `tests/unit/test_traceparent_propagation.py`. No prior test was edited; the append-only
  gate ran clean without `--skip-append-only`.
- **Commits:** see `Refs: OME-1185`.
- **Gates:** `uv run .claude/scripts/run_gates.py screamingface-engine` — ALL GATES GREEN
  (append-only check, ruff check, ruff format, pyright, check_layering, pytest with coverage).
  Full engine suite: 3071 passed, 16 skipped.
- **Mutation testing:** 7 mutations tried, 7 killed —
  (1) `current_traceparent` ignoring the node span → 4 tests died;
  (2) dropping the `NodeStarted` bind → 2;
  (3) `run_trace_scope` not clearing the node span on entry → 1;
  (4) binding AFTER the bridge's overflow guard instead of before → 1;
  (5) binding on `NodeFinished` instead of `NodeStarted` → 2;
  (6) binding `parent_span_id` instead of the node's own `span_id` → 2;
  (7) rendering a node span with no run bound → 1.
  No assertion walks a `repr()`; the end-to-end test reads `Traced.span.span_id` and
  `SpanData.request_model` off the actual frames.
- **Deviations:** none. The ordering question is settled in D2 above (accepted, with the
  reasoning), which is the ticket's explicit ask.
- **Owner-verify:** a deployed multi-node run should now render each aigateway span under its
  calling node rather than all of them under the run's root — the production counterexample is
  trace `e2f0bfb83234b51d0228ce0fa39c0334`.
