---
id: OME-1955
linear_url: https://linear.app/openmined/issue/OME-1955/refresh-the-curated-openrouter-model-list
status: in_review
type: feature
priority: medium
labels: [aigateway, agentic, autonomous]
parent: OME-1315
created: 2026-11-17
closed:
---

# Refresh the curated OpenRouter model list

`sf.models.list()` does not show the current models of the large labs. The curated list was last
updated in August 2026. Owner decision 2026-11-17: keep the curated list, add the new models, and
add a command that shows when the list is out of date. The Engine listing rule does not change,
and no model leaves the list.

This ticket is PR A: 49 OpenRouter models in the gateway list and the Engine copy, and
`apps/aigateway/scripts/check_openrouter_seeds.py`.

- Spec: `docs/spec/2026-11-17-OME-1955-refresh-curated-model-list.md`
- Plan: `docs/plan/2026-11-17-OME-1955-refresh-curated-model-list.md`
- Ledger: `docs/work/2026-11-17-OME-1955-refresh-curated-model-list.md`
- Sub-issues: `OME-1956` (the newest OpenRouter models first), `OME-1957` (search with words, public docs).
- Related: `OME-816`, `OME-972`, `OME-878`.
