---
id: OME-1615
linear_url: https://linear.app/openmined/issue/OME-1615/the-ai-gateway-downloads-litellms-model-list-on-every-start-so
status: done
type: bug
priority: none
labels: [bug, aigateway, agentic]
created: 2026-10-15
closed: 2026-10-15
---

# The AI Gateway downloads litellm's model list on every start, so OpenRouter reasoning calls broke when that list changed

litellm loads its model list (which models exist, which parameters each accepts) once, at import,
and by default downloads it from its GitHub main branch. On 2026-10-15 the downloaded list had
lost all 269 OpenRouter entries, so litellm refused `reasoning_effort` for every OpenRouter model
before any call left the gateway: the paid smoke lost 278 of 278 calls to its reasoning member.
The gateway package now sets `LITELLM_LOCAL_MODEL_COST_MAP=True` before litellm loads, so the
list is the one bundled with the litellm version in `uv.lock`. Filed in Triage as a `bug` under
OME-1320 (LiteLLM dependency management), for owner review. Ledger:
`../work/2026-10-15-pin-litellm-model-map.md`.
