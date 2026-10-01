---
id: OME-1217
linear_url: https://linear.app/openmined/issue/OME-1217/stop-emitting-server-spans-for-health-check-probes
status: in_review
type: improvement
priority: 2
labels: [aigateway, agentic, autonomous]
created: 2026-09-17
closed:
---

# Stop emitting server spans for health-check probes

`GET /healthz` was 60.2% of aigateway's spans (14,403 / 23,906 in 24h), as ROOT spans that bury
real requests in the trace list. Server spans come from `middleware/call_id.py`, not
`FastAPIInstrumentor`, so the stock OTel knob had no effect. Owner decision (2026-10-01, option
A): build the span, flag it once routing resolves a probe route, drop it in a SpanProcessor.
`OTEL_PYTHON_EXCLUDED_URLS` (OTel semantics), default `^/healthz$`. Related: `OME-1218`.

Canonical artifacts:

- Ledger: `docs/work/2026-10-01-skip-probe-server-spans.md`
