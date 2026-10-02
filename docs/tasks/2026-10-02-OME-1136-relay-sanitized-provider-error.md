---
id: OME-1136
linear_url: https://linear.app/openmined/issue/OME-1136/every-rejected-model-call-says-only-the-upstream-provider-returned-an
status: in_progress
type: feature
priority: high
labels: [aigateway, agentic, autonomous]
parent: OME-1317
created: 2026-10-02
closed:
---

# Every rejected model call says only "the upstream provider returned an error"

Relay a sanitized upstream message (`upstream_status` / `upstream_message` + composed
`message`) on every gateway error code except 401/429. Ledger:
`docs/work/2026-10-02-ome-1136-relay-sanitized-provider-error.md`.
