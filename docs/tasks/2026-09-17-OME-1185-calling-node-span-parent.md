---
id: OME-1185
linear_url: https://linear.app/openmined/issue/OME-1185/send-the-calling-nodes-span-id-to-aigateway-not-the-runs-root
status: in_review
type: feature
priority: 4
labels: [screamingface-engine, agentic, autonomous]
created: 2026-09-11
closed:
---

# Send the calling node's span id to aigateway, not the run's root

`trace_scope` binds the run's `root_span_id`, so every aigateway server span attaches to the
run's root and the trace is connected but flat — in production trace
`e2f0bfb83234b51d0228ce0fa39c0334` all 24 aigateway server spans shared the single parent
`c84b53aff1cdcb16`, so no gateway call can be attributed to the node that made it. `OME-1130` made per-node spans real, so the per-node parent
no longer dangles. Bind the CURRENT node's span id instead, and record the decision on the
ordering question (the node's `SpanEvent` is published on finish, after the gateway span that
names it).

Ledger: `docs/work/2026-09-17-OME-1185-calling-node-span-parent.md`
