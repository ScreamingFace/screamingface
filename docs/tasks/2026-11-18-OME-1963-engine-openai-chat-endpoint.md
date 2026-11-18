---
id: OME-1963
linear_url: https://linear.app/openmined/issue/OME-1963/serve-an-ensemble-through-an-openai-compatible-chat-endpoint-on-the
status: in_review
type: feature
priority: high
labels: [screamingface-engine, agentic, autonomous]
parent: OME-1297
created: 2026-11-18
closed:
---

# Serve an ensemble through an OpenAI-compatible chat endpoint on the Engine

The Engine gets `POST /v1/chat/completions`, a route that is compatible with the OpenAI
chat-completions API. A user can run an ensemble from an OpenAI SDK or from an agent (pi,
opencode) with a base URL and a model name. The `model` field is a Candidate URL4 or one gateway
model id. The route gives the usual chat-completion JSON, a buffered stream, client tools through
the final step, and the OpenAI error envelope.

- Parent epic: `OME-1297` (E8, chosen by the owner on 2026-11-18).
- Spec: `docs/spec/2026-11-17-engine-openai-chat-endpoint/`
- Plan: `docs/plan/2026-11-17-engine-openai-chat-endpoint.md`
- Ledger: `docs/work/2026-11-17-engine-openai-chat-endpoint.md`
- The same PR has the docs page (`OME-1964`) and the repo script changes (`OME-1965`).
- Deploy order: workers first, then the App.
