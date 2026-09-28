---
id: OME-1119
linear_url: https://linear.app/openmined/issue/OME-1119/propagate-the-traceparent-from-the-engine-to-aigateway
status: done
type: null
priority: 2
labels: [screamingface-engine, agentic, autonomous]
created: 2026-09-07
closed: 2026-09-07
---

# Propagate the traceparent from the engine to aigateway

Rung 2 of the correlation ladder, second child of the Phase 1 epic (`OME-1118`). The engine
adopted a caller's traceparent and told nobody — the header set aigateway received carried
`X-User-Email` and `X-Profile` but no `traceparent`, so the trace stopped at the engine and a
user quoting their `trace_id` saw nothing about the model calls.

Two sources, because there are two kinds of caller:

- **Run mode** — a ContextVar bound inside the executor's driving task, from the `TraceContext`
  `url4.streaming.lifecycle.run` hands to `Executor.execute`. Not from `logs.RunContext`, which
  is `None` whenever the caller sent no traceparent and url4 minted one instead.
- **Connections** — carried on `Caller`, which already is the per-request object. One
  `_headers(caller)` covers every upstream call, and `/v1/providers` gains the `X-Profile` it
  had also been missing.

The **catalog path deliberately sends nothing**: `CachedCatalog` coalesces concurrent misses
onto one upstream fetch, so that call has many causes and no single honest trace. Documented at
the call site; a span Link is Phase 2 (`OME-1130`).

Ledger: `docs/work/2026-09-07-OME-1119-engine-propagates-traceparent.md`
