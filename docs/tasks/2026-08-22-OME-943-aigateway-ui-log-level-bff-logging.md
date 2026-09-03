---
id: OME-943
linear_url: https://linear.app/openmined/issue/OME-943/wire-or-delete-aigateway-ui-log-level-and-log-bff-errors-server-side
status: backlog
type: improvement
priority: 3
labels: [aigateway, agentic, autonomous]
created: 2026-08-22
closed:
---

# Wire or delete aigateway-ui LOG_LEVEL and log BFF errors server-side

The chart renders a `LOG_LEVEL` env that nothing reads — wire it or delete it. Add minimal
BFF server-side logging: one line per BFF error (path, `AdminErrorKind`, request id) —
today a BFF 500 logs nothing. Never log upstream response bodies.

Canonical artifacts:

- Spec: `docs/spec/2026-08-22-observability-traceability-review.md`
