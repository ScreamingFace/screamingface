---
id: OME-873
linear_url: https://linear.app/openmined/issue/OME-873/route-aigateways-colon-bearing-model-ids-via-a-encoding
status: In Review
type: task
priority: Medium
labels: [url4-cloud, agentic, autonomous]
created: 2026-08-18
closed:
---

# Route aigateway's colon-bearing model ids via a `~` encoding

Makes the 29 `aigateway_only` model ids (colon-bearing, e.g.
`huggingface/openai/gpt-oss-120b:cerebras`) routable from a url4 expression by remapping
`:` → `~` at the route boundary and reverting at the single point the real request reaches
aigateway. Also extends `GET /v1/models` / `GET /v1/model-parameters` to advertise these ids
in their encoded form.

Full detail and design rationale: the Linear issue body (brainstormed and approved in chat,
bounded path — no separate spec doc).
