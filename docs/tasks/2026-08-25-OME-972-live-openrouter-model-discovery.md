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
cached in a process-local snapshot shared across accounts (TTL 300 s, stale 3600 s,
single-flight), published through
`GET /v1/models` with snapshot-or-fallback semantics — discovered plain IDs + explicitly
configured operator models + admitted models when healthy; compiled/operator seeds + admitted
when cold or degraded. Default-on behind `AIGW_OPENROUTER_LIVE_MODELS`.

- Ledger: `docs/work/2026-08-25-OME-972-live-openrouter-model-discovery.md`
- Standalone task; NOT a child of OME-308. Related: OME-492, OME-878, OME-879.

## Follow-ups

1. **`plugins/openrouter_provider/plugin.py` exceeds the 450-line split discipline** — 558 lines
   (526 before this unit; +32 for the discovery/live-listing port pair). Proposed fix: extract
   the discovery/live-listing hooks into a cohesive module.
2. **`is_online_variant` is case-sensitive**, so `openrouter/<a>/<m>:Online` is still
   configurable and unpoliced at dispatch. The predicate is shared with OME-712's dispatch
   refusal and the global-cache bypass, so the fix belongs in one place, in its own unit.
3. **Colon variants are not auto-published** (deferred by design); tilde aliases should later
   fold to canonical ids via `alias_target` rather than being published raw.
4. **Census drift vs truncation share one reason token.** `total_count` legitimately moves
   between page fetches upstream (measured 418 → 419 seconds apart), so a drifting refresh is
   reported as `model_catalog_truncated`. A distinct reason would let operators separate benign
   drift from real page loss.
