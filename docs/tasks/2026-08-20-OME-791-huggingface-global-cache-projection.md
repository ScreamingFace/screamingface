---
id: OME-791
linear_url: https://linear.app/openmined/issue/OME-791/implement-the-huggingface-global-cache-projection
status: Backlog
type: improvement
priority: low
labels: [aigateway, agentic, autonomous]
parent: OME-787
created: 2026-08-20
closed:
---

# Implement the HuggingFace global-cache projection

Give the HuggingFace provider a pure `global_cache_projection` so its chat-parameter rules can
be promoted from `cache_behavior="bypass"` to `"keyed"`, enabling AIGateway's global
exact-response cache for `huggingface/*` non-streaming Chat Completions. This is gateway
response replay, not any HF-side prompt caching.

`status` above is the real Linear status. The owner directed mid-session that Linear must not be
modified during this work, so the issue was deliberately NOT transitioned to In Progress and no
Linear comment was posted. Reconcile Linear manually.

## Scope

- Add a pure provider-local projection and `GLOBAL_CACHE_ADAPTER_REVISION` in a new
  `plugins/huggingface_provider/global_cache.py`, following the `openrouter_provider` /
  `openai_provider` module shape rather than Anthropic's in-plugin form.
- Project the two output-affecting things the HF boundary adds: the pinned router `api_base`
  and the upstream model identity implied by the gateway slug.
- Promote every `bypass` rule in `plugins/huggingface_provider/parameters.py` to `keyed`,
  including `cache_behavior="keyed"` on `function_calling_rules(...)`, only once the real
  projection exists.
- Bypass unsuffixed `huggingface/<org>/<model>` ids: without `:<provider|policy>` the router
  picks a backend per request, so no single upstream describes the next call.
- Fail closed on a non-official `AIGW_HUGGINGFACE_ROUTER_API_BASE`: the projection must stay
  pure, so the deployment-local override is checked in the impure participation hook instead.
- Add `cache_reference_from_cached_response` returning `None` — HF contributes no
  usage-accounting strategy, and a missing hook logs a false mapper failure on every hit.
- Add purity/determinism, malformed-and-unsuffixed bypass, key-difference, route miss->hit,
  and hit-does-no-credential-work proofs.

## Acceptance

- Identical eligible `huggingface/*` requests produce `miss -> hit`.
- Different repos, different `:<backend>` suffixes, different messages, and different values of
  any newly-keyed parameter do not collide.
- The projection is total, deterministic, non-mutating, JSON-safe, identity-free,
  credential-free, reads no settings, and performs no I/O.
- Malformed and unsuffixed model ids never read or write cache, using the same predicates the
  provider already owns.
- A hit performs no HF credential work and no provider dispatch.
- Existing OpenRouter, Anthropic and Codex behaviour remains unchanged; no core port change.
- No database model, migration, dependency, or persistence-format change.
- Focused tests and the complete AIGateway quality gate pass.

## Out of scope

Streaming, `top_p` promotion, the sibling OME-787 projections (OME-788 Anthropic promotion,
OME-789 Gemini, OME-790 Antigravity, OME-792 Ollama), `X-HF-Bill-To`, HF usage-accounting
strategy, runtime model discovery, gateway-owned aliases, cache retention, schema changes, and
cost estimation.
