---
id: OME-864
linear_url: https://linear.app/openmined/issue/OME-864/add-direct-openai-platform-api-key-provider-to-aigateway
status: Pick Immediately
type: Feature
priority: Urgent
labels: [aigateway, agentic, autonomous]
created: 2026-08-17
closed:
---

# Add direct OpenAI Platform API-key provider to AIGateway

Add API-key-only direct OpenAI access under `openai/*` without changing the existing
`codex/*` OAuth or `openrouter/openai/*` routes.

Canonical artifacts:

- Spec: `docs/spec/2026-08-17-OME-864-direct-openai-provider.md`
- Plan: `docs/plan/2026-08-17-OME-864-direct-openai-provider.md`

Offline source implementation and deterministic verification are complete on the dedicated branch.
The owner-supplied bounded live pass verified `openai/gpt-5-nano` readiness, all fourteen concrete
seed IDs in the account catalog and Chat Completions, and one end-to-end AIGateway route request.
OME-864 has no remaining code or provider-verification blocker. Per owner instruction, Linear
OME-864 remains unchanged for now; the separate OpenAI caching issue will be filed later.
