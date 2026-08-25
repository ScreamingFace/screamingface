---
id: OME-972
linear_url: https://linear.app/openmined/issue/OME-972/aigateway-automatically-discover-models-offered-by-openrouter
status: In Progress
type: feature
priority: 2
labels: [aigateway]
created: 2026-08-24
closed:
---

# AIGateway: automatically discover models offered by OpenRouter

Live model discovery for the OpenRouter provider: bounded async fetch of the public catalog,
cached deployment-wide snapshot (TTL 300 s, stale 3600 s, single-flight), published through
`GET /v1/models` with snapshot-or-fallback semantics — discovered plain IDs + explicitly
configured operator models + admitted models when healthy; compiled/operator seeds + admitted
when cold or degraded. Default-on behind `AIGW_OPENROUTER_LIVE_MODELS`.

- Ledger: `docs/work/2026-08-25-OME-972-live-openrouter-model-discovery.md`
- Standalone task; NOT a child of OME-308. Related: OME-492, OME-878, OME-879.
