---
id: OME-884
linear_url: https://linear.app/openmined/issue/OME-884/support-global-exact-response-caching-for-direct-openai
status: Done
type: improvement
priority: medium
labels: [aigateway, agentic, autonomous]
parent: OME-787
created: 2026-08-19
closed: 2026-09-03
---

# Support global exact-response caching for direct OpenAI

Enable AIGateway's global exact-request cache for direct `openai/*` non-streaming Chat
Completions. This is gateway response replay, not OpenAI prompt caching.

## Scope

- Add a pure provider-local global-cache projection and adapter revision for `openai/*`.
- Treat every syntactically valid `openai/*` model as dispatchable and cacheable;
  `OpenAIPluginSettings.default_models` is the bootstrap `/v1/models` catalog, not a dispatch
  or cache allowlist.
- Promote `max_tokens` from `cache_behavior="bypass"` to `"keyed"` only once the real
  projection exists.
- Fail closed for unsafe ambient OpenAI/LiteLLM state and for ambient LiteLLM model redirects
  of the exact requested model.
- Post-commit review addition (owner decision, cycle 2): handle `litellm.modify_params`, the
  ambient LiteLLM flag that rewrites `max_tokens` after the cache key is built. It declines
  direct OpenAI cache participation outright, and refuses live dispatch ONLY when the effective
  `max_tokens` is not `None` — a request without a ceiling is one LiteLLM never modifies and
  stays live-dispatchable, merely uncached.
- Ensure a cache hit performs no OpenAI provider-credential work and no provider dispatch; the
  existing `aigateway:index` profile-index read remains an accepted pre-cache cost.
- Add purity, custom-model miss/hit, key-difference, malformed-model, cross-account, and
  provider-credential-isolation proofs.

## Acceptance

- Identical eligible requests produce `miss -> hit`.
- Different models, messages, system content, or effective `max_tokens` values do not collide.
- A locally configured or directly addressed syntactically valid custom model can produce
  `miss -> hit`; removing it from `default_models` only removes it from the published catalog.
- The projection is deterministic, non-mutating, identity-free, credential-free, and performs
  no I/O.
- Malformed model IDs never read or write cache. A syntactically valid unsupported model is
  rejected by OpenAI on a miss and its unsuccessful response is not stored.
- After a successful store, a hit intentionally does not re-check current provider availability
  or caller access; this is the accepted exact-replay and cross-account behaviour.
- Existing Codex, Anthropic and OpenRouter behaviour remains unchanged.
- No database model, migration, dependency, or persistence-format change.
- Focused tests and the complete AIGateway quality gate pass.

## Out of scope

Responses API, streaming, tools, new request parameters, provider prompt caching, runtime model
discovery, gateway-owned aliases, accounting expansion, cache retention, schema changes, and
cost estimation.
