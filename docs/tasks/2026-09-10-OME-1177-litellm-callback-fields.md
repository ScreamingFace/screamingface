---
id: OME-1177
linear_url: https://linear.app/openmined/issue/OME-1177/strip-new-litellm-11000-dynamic-callback-params-in-request-hardening
status: in_review
type: task
priority: 3
labels: [aigateway, agentic, autonomous, task]
created: 2026-09-10
---

# OME-1177 — strip new LiteLLM 1.100.0 dynamic callback params in request hardening

litellm 1.100.0 adds three new dynamic callback params
(`langfuse_environment`, `newrelic_api_key`, `newrelic_region`) not yet stripped by
aigateway's `_CALLBACK_DYNAMIC_FIELDS` allowlist — a telemetry-redirect exfiltration gap.
Blocks GitHub PR #858. See `docs/work/2026-09-10-OME-1177-litellm-callback-fields.md`.

Telemetry follow-up: `docs/work/2026-09-10-OME-1177-otel-metadata-ingress.md`. Implemented and validated; PR #903 awaits review/merge.
