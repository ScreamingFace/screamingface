---
id: OME-1120
linear_url: https://linear.app/openmined/issue/OME-1120/join-the-inbound-traceparent-to-aigateways-log-context-and-echo-it
status: done
type: null
priority: 2
labels: [aigateway, agentic, autonomous]
created: 2026-09-10
closed: 2026-09-10
---

# Join the inbound traceparent to aigateway's log context and echo it

Rung 4b — the payoff rung, and the last one. With this, **all five ladder rungs pass**: one
`trace_id` spans client → engine → gateway logs, which is Phase 1's local acceptance in full.

Three things worth knowing before touching this area:

- **The `traceparent` header is caller-controlled.** Adopting a malformed or attacker-chosen
  value would let a caller pick the key other requests are grouped under, so anything that
  does not parse is REPLACED, never cleaned up. Nine rejection cases are pinned in
  `tests/unit/test_trace_context.py` — that table is the security half of this unit, and the
  e2e rung does not cover it (the client always sends a well-formed header).
- **The W3C rule is mirrored, not imported** — `apps/aigateway` has no `url4` dependency, so
  the rule lives in three places. Each copy asserts its own rejection table so a divergence
  fails a test.
- **`_aigw.trace_id` is a published response-contract change.** The schema declares
  `additionalProperties: false`; the field was added optional so older payloads still validate.

Ledger: `docs/work/2026-09-10-OME-1120-gateway-joins-trace.md`
