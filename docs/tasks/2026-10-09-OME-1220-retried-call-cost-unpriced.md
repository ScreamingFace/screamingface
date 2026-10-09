---
id: OME-1220
linear_url: https://linear.app/openmined/issue/OME-1220
status: in_review
type: bug
priority: high
labels: [bug, screamingface-engine, agentic]
created: 2026-09-17
---

# Make retried model-call cost unpriced without idempotency evidence

After a lost reply, the Engine connector retries a gateway call once. The lost attempt may
already have been billed upstream: a non-streaming provider call is charged in full even when the
gateway cancels it after the caller disconnects. A retried miss still reported only the answering
attempt's price, and a retried hit reported `"0"` at the operation level. Both understated spend.

Ledger: `docs/work/2026-10-09-retried-call-cost-unpriced.md`.

- 2026-09-17: filed (parent epic OME-1287).
- 2026-10-09: owner decisions. A round trip retried after a failure that may have reached the
  gateway is unpriced at call, operation and run level. A connect-phase failure (`ConnectError`,
  `ConnectTimeout`, `PoolTimeout`) proves nothing was sent, so it keeps the exact price.
  A gateway idempotency key is out of scope and will be proposed separately. Implemented; gates
  are green; PR opened.
