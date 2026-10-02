---
id: OME-1250
linear_url: https://linear.app/openmined/issue/OME-1250/connection-status-can-report-connected-while-every-provider-call-fails
status: in_review
type: bug
priority: medium
labels: [aigateway, agentic, task, bug]
parent: OME-1317
created: 2026-10-02
closed:
---

# Connection status can report 'connected' while every provider call fails

Owner decision (2026-10-01/02): outcome-driven status, staged rollout, strict decoding.

- **PR1 (step 1, consumers):** the Engine and the SDK accept a new `unavailable` status
  (authenticates, cannot serve: 402 / quota), distinct from `error` (credential rejected).
  Decoding stays strict.
- **PR2 (step 2, gateway, stacked):** `degraded_until` / `degraded_reason` columns plus
  migration; a 402 or quota failure opens a 15-minute window, each one extends it, any success
  clears it, 5xx never degrades, 401 unchanged; `GET /v1/provider-access` emits `unavailable`.
  DO NOT MERGE before PR1 is deployed and the SDK is published.

Ledger: ../work/2026-10-01-connection-status-outcome-driven.md
