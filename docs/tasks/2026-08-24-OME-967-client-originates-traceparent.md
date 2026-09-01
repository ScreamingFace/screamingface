---
id: OME-967
linear_url: https://linear.app/openmined/issue/OME-967/originate-the-traceparent-in-the-client-and-surface-trace-id-to-the
status: backlog
type: improvement
priority: 2
labels: [py-screamingface, agentic, autonomous]
created: 2026-08-24
closed:
---

# Originate the traceparent in the client and surface trace_id to the user

The keystone of the correlation roadmap — ahead of Phase 1. The trace id is minted inside
the Runner Job and never returned, so every failure before the first frame (capability
mint, run start, WS handshake) has no id at all and is unjoinable forever. The engine
already adopts an inbound traceparent, so this is client-side only. Also surface the id on
the run outcome, on `ExecutionError`, and in `runtime.log` — today the client holds the
traceparent with zero read sites.

Canonical artifacts:

- Spec: `docs/spec/2026-08-22-observability-traceability-review.md` (§4, §6 keystone)
