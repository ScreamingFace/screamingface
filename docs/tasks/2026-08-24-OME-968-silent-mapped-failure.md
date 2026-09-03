---
id: OME-968
linear_url: https://linear.app/openmined/issue/OME-968/a-mapped-provider-failure-returns-500-and-logs-nothing-at-all
status: backlog
type: improvement
priority: 2
labels: [aigateway, agentic, autonomous]
created: 2026-08-24
closed:
---

# A mapped provider failure returns 500 and logs nothing at all

Empirically observed: a mapped litellm `APIConnectionError` returns `provider_unavailable`
and emits zero WARNING/ERROR records — an operator alerting on WARNING+ sees nothing.
Successful streams emit zero records entirely; failed streams log only a plugin class name
at HTTP 200. Every terminal failure path must emit one structured record carrying the
request's `gateway_call_id`. Depends on `OME-938`; complements `OME-939` (which covers
unhandled, not mapped, exceptions).

Canonical artifacts:

- Spec: `docs/spec/2026-08-22-observability-traceability-review.md` (§4)
