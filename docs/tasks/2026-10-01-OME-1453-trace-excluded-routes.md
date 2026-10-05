---
id: OME-1453
linear_url: https://linear.app/openmined/issue/OME-1453/stop-reusing-otel-python-excluded-urls-for-route-template-matching-in
status: done
type: improvement
priority: 4
labels: [aigateway, agentic, autonomous]
created: 2026-10-01
closed: 2026-10-02
---

# Stop reusing OTEL_PYTHON_EXCLUDED_URLS for route-template matching in aigateway

Follow-up from the review of `OME-1217`. The probe-span exclusion matched the standard OTel
variable against route templates, so a cluster-wide unanchored value (e.g. `healthz,models`)
would silently drop real routes such as `/v1/models`. Decision: rename to the gateway-specific
`AIGW_TRACE_EXCLUDED_ROUTES` (anchored regex list, default `^/healthz$`), read through
`Settings`; `OTEL_PYTHON_EXCLUDED_URLS` is no longer honoured. Related: `OME-1218`.

Canonical artifacts:

- Ledger: `docs/work/2026-10-01-trace-excluded-routes-setting.md`
