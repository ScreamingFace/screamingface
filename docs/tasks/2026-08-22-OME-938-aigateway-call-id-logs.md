---
id: OME-938
linear_url: https://linear.app/openmined/issue/OME-938/carry-gateway-call-id-on-every-aigateway-log-line
status: backlog
type: improvement
priority: 2
labels: [aigateway, agentic, autonomous]
created: 2026-08-22
closed:
---

# Carry gateway_call_id on every aigateway log line

Request-scoped contextvar + record-factory injection (wrapping — never replacing — the
redaction factory that owns the single `setLogRecordFactory` slot) so every log line of a
request carries the call id, not just the one accounting line. Id generation moves to thin
middleware so `AIGW_TAXONOMY_ENABLED=false` no longer silently deletes correlation. No
LiteLLM callbacks; never log bodies. Prerequisite for Phase 1 trace continuity.

Canonical artifacts:

- Spec: `docs/spec/2026-08-22-observability-traceability-review.md`
