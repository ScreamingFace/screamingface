---
id: OME-1170
linear_url: https://linear.app/openmined/issue/OME-1170/checking-a-models-parameters-fails-with-http-504-the-first-time-after
status: done
type: fix
priority: Medium
labels: [screamingface-engine, agentic, autonomous]
created: 2026-09-10
closed: 2026-09-10
---

# Checking a model's parameters fails with HTTP 504 the first time after a stack start

On a fresh stack, the engine gives the gateway 10s per catalog/datasheet fetch,
but a cold gateway composes a model's parameter datasheet in 3–11.8s — the
timeout loses, the engine answers 504, and the SDK's free pre-spend check dies
with a hard PlanningError even though the failed attempt just warmed the
gateway's cache. Fix: raise the upstream timeout to 30s (above the measured
cold ceiling) and retry once on a timeout only — the retry is nearly free. A
down gateway still fails bounded (two attempts) as CatalogUnavailable; the
warm ~2ms path is untouched. Details + evidence: Linear issue; how: ledger
`docs/work/2026-09-10-OME-1170-catalog-timeout-retry.md`.
