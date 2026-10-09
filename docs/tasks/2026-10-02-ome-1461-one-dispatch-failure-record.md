---
id: OME-1461
linear_url: https://linear.app/openmined/issue/OME-1461/keep-gateway-dispatch-failures-at-exactly-one-record-when-the-failure
status: in_review
type: task
priority: low
labels: [aigateway, agentic, autonomous]
parent: OME-1317
created: 2026-10-02
closed:
---

# Keep gateway dispatch failures at exactly one record when the failure handler itself raises

When `_dispatch_failure_response` raises, the request now emits one `dispatch failed` record
carrying `outcome=handler_error handler_type=<Class>` instead of two ERROR records. Log levels:
499 → INFO, 429 → WARNING, gateway back-pressure 503 → WARNING, upstream/unknown 503 → ERROR, other 5xx → ERROR, other 4xx → WARNING (policy in the ledger).

- 2026-10-02: work started on branch
  `bershadsky/ome-1461-keep-gateway-dispatch-failures-at-exactly-one-record-when`, ledger
  `docs/work/2026-10-02-ome-1461-one-dispatch-failure-record.md`.
