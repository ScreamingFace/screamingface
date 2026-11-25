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

## Added on 2026-11-24

- **The one-line change from the OpenAI SDK (U10, spec §5.6).** `sf.Client` and
  `sf.AsyncClient` accept the arguments of the OpenAI client (`api_key` is accepted, not kept
  and not sent; `base_url` is the Engine URL; `timeout` and `max_retries` are the defaults of
  the chat calls). `create` accepts each keyword of the OpenAI `create`, and the reply types
  have `model_dump()`, `model_dump_json()` and `to_json()`. Not in scope, by owner decision: a
  map of OpenAI model names, the OpenAI error classes, the other OpenAI APIs.
- **Tool calls are turned off for now (U11, spec §5.7).** A chat call that declares or uses a
  tool raises `PlanningError`, code `tools_not_available`, before a request. The Engine route
  has the same check (`OME-1963`). The refusal is fixed, with no switch; the tool code stays.
