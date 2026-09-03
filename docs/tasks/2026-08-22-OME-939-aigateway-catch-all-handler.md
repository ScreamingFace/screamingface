---
id: OME-939
linear_url: https://linear.app/openmined/issue/OME-939/add-an-aigateway-catch-all-exception-handler-class-name-only-call-id
status: backlog
type: improvement
priority: 3
labels: [aigateway, agentic, autonomous]
created: 2026-08-22
closed:
---

# Add an aigateway catch-all exception handler (class-name-only + call id)

Today an unhandled exception outside the chat route is an uncaught ASGI 500 — no app log
line, no id, no audit. Add a catch-all handler logging class-name-only + `gateway_call_id`
with a structured 500, audit-parity with the admin APIRoute pattern. The privacy posture
(no tracebacks, no provider text) is preserved; its amendment is a later, sink-gated phase.

Canonical artifacts:

- Spec: `docs/spec/2026-08-22-observability-traceability-review.md`
