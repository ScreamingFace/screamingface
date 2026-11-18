---
id: OME-1956
linear_url: https://linear.app/openmined/issue/OME-1956/list-the-newest-openrouter-models-first-in-the-gateway-model-list
status: in_review
type: feature
priority: medium
labels: [aigateway, agentic, autonomous]
parent: OME-1955
created: 2026-11-17
closed:
---

# List the newest OpenRouter models first in the gateway model list

The gateway listed the discovered OpenRouter models in alphabetical order. It now reads the release
date of each catalogue row and lists the discovered models newest first. The row content does not
change, so the Engine and the Client need no change.

- Spec and plan: `docs/spec/2026-11-17-OME-1955-refresh-curated-model-list.md` §5.2 and
  `docs/plan/2026-11-17-OME-1955-refresh-curated-model-list.md` §3 (in the PR of `OME-1955`).
- Ledger: `docs/work/2026-11-17-openrouter-newest-first.md`
