---
id: OME-2005
linear_url: https://linear.app/openmined/issue/OME-2005/call-an-ensemble-as-a-chat-model-from-the-sdk-chat-on-recipes-and
status: in_review
type: feature
priority: high
labels: [client-sf, agentic, autonomous]
parent: OME-1297
created: 2026-11-23
closed:
---

# Call an ensemble as a chat model from the SDK (chat on recipes and clients)

The ScreamingFace SDK gets chat calls in the shape of the OpenAI client. They call the Engine
route `POST /v1/chat/completions` of `OME-1963`. A user can call an ensemble as a chat model
with no new object: `recipe.chat.completions.create(...)`, `sf.Client().chat`,
`sf.AsyncClient().chat` and the module twin `sf.chat`, each with `completions.create(...)`
and `endpoint()`. The replies have the OpenAI field names plus the `screamingface` extension.

- Parent epic: `OME-1297` (E8).
- Spec: `docs/spec/2026-11-18-sdk-model-inference/`
- Plan: `docs/plan/2026-11-18-sdk-model-inference.md`
- Ledger: `docs/work/2026-11-18-sdk-model-inference.md`
- The same PR as `OME-1963` (#1937), by owner decision on 2026-11-23.
- One small Engine change (U1): the stream error event gets `should_retry` and `retry_after`;
  a tool-call reply with no text has `content: null`.
