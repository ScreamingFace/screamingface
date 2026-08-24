# OME-791 spec — HuggingFace global exact-response cache

Linear: `OME-791` (parent `OME-787`). Stack: `apps/aigateway`.
Companion plan: `docs/plan/2026-08-20-OME-791-huggingface-global-cache-projection.md`.

## 1. Problem

`huggingface_provider` has no `global_cache_projection`. It inherits the `CacheBypass` default
from `ProviderPluginBase`, so **every** `huggingface/*` request bypasses AIGateway's global
exact-response cache at the projection step, whatever its parameter rules say. Consequently all
ten of its ordinary rules plus `tools`/`tool_choice` are declared `cache_behavior="bypass"`, and
`plugins/huggingface_provider/parameters.py:46-63` records that this is a disposition forced by
the missing projection rather than a judgement about the parameters.

The product cost: a benchmark re-run over HF models pays full price every time, while the same
suite over OpenRouter replays for free.

## 2. MVP semantics

- Cacheable unit: non-streaming Chat Completions through the unified HF router.
- A gateway model id is `huggingface/<org>/<model>[:<provider|policy>]`, validated by the
  existing `_validate_model_slug`.
- **Only a backend-pinned id is cacheable.** An id carrying `:<provider|policy>` names one
  upstream inference provider. An id without it does not: `pinned_router_target` already
  records that "without `:<provider>` the router selects a backend PER REQUEST, so no single
  backend row describes the next call". Replaying one backend's answer for a request the router
  would have sent elsewhere would corrupt model attribution, which for a benchmark product is a
  wrong answer rather than a stale one. Unsuffixed ids therefore bypass.
  Cost of this restriction is approximately zero: all 24 entries in `_default_model_slugs()`
  are backend-pinned.
- `default_models` is the bootstrap `/v1/models` catalog. Consistent with the OME-884 ruling for
  OpenAI, it is not a cache allowlist; any route-valid backend-pinned id projects.
- A hit re-checks nothing. HF validates model existence, backend availability and token
  permission on the miss that filled the row. A later hit performs no availability and no access
  check, so an exact replay may still answer after a backend has been withdrawn or has become
  unavailable to the current caller. This is the approved exact-replay and cross-account
  behaviour inherited from OME-305, not a new decision.

## 3. Model identity

`resolved_model` is the UPSTREAM id: the gateway slug with the `huggingface/` prefix removed,
i.e. `<org>/<model>:<backend>`.

This is pinned by installed-transform evidence, not assumed.
`tests/unit/huggingface/test_huggingface_dispatch.py:29-46` drives the installed
`HuggingFaceChatConfig.transform_request` and asserts the post-strip model reaches the outbound
body **verbatim** as `deepseek-ai/DeepSeek-R1:novita`; `:48-57` pins the URL as
`{api_base}/chat/completions`.

Because the `:<backend>` suffix is part of the upstream id, two different backends for one repo
key differently as a structural consequence of `resolved_model`, with no separate mechanism.

The same test records the precondition that makes this deterministic at all: with `api_base`
pinned, litellm's `_fetch_inference_provider_mapping` is never called. Unpinned, litellm would
resolve a provider mapping over the network keyed by ambient `HUGGINGFACE_API_KEY`, and the
upstream model reaching the wire would stop being a function of the request. The pinned base is
therefore a cache-correctness precondition, not only a credential-safety one.

## 4. Key material

`prepared` describes everything the HF boundary adds that the caller did not send.
`prepare_chat_body` (`plugin.py:208-230`) does exactly three things:

| Transformation | Classification |
|---|---|
| `out["api_base"] = self.settings.router_api_base` | **Output-affecting** — which endpoint answers. Projected. |
| `out.pop("api_key")` | Transport. The gateway owns the credential; a caller copy would be overwritten regardless. Excluded, as OpenRouter excludes its injected key. |
| `extra_headers` auth-name sanitisation and empty/non-dict drop | Transport. Excluded — see §7. |

So `prepared` is `{"api_base": OFFICIAL_ROUTER_API_BASE}`.

`GLOBAL_CACHE_ADAPTER_REVISION` carries what the JSON-hashed `prepared` cannot: the installed
litellm HuggingFace transform behaviour (verbatim model pass-through, the
`{api_base}/chat/completions` URL, and the absence of a provider-mapping fetch). A litellm
upgrade that changes any of those is a mandatory bump.

### Identity exclusion

The key contains no account, profile, credential, organisation or backend-billing identity. HF
injects no attribution header today — there is no `bill_to` / `X-HF-Bill-To` anywhere in `src`
or `tests`, so nothing account-derived reaches the wire. Adding one later changes the request
per account and is a mandatory revision bump **and** a cross-account replay re-decision.

## 5. Purity versus admission

The projection is pure key material. The deployment-local question "may this provider use the
cache here at all" belongs to `participates_in_global_cache`, which is allowed to read settings.

`HuggingFacePluginSettings.router_api_base` is an env-overridable field
(`AIGW_HUGGINGFACE_ROUTER_API_BASE`). This is the one structural difference from every existing
projection: OpenRouter and OpenAI both pin an unconfigurable module constant, so neither can
diverge. HuggingFace can.

A pure projection may not read that field — the purity sweep passes a settings object that
raises on attribute access, and a per-host settings read would make one host's keys differ from
another's while each host's own determinism test still passed, which is worse than failing.

Resolution: the projection emits the official constant; the participation hook declines
participation entirely when `self.settings.router_api_base` is not that constant. A deployment
pointing HF at a proxy or a mock therefore neither reads nor writes global rows, instead of
sharing a key that misdescribes its endpoint.

## 6. Parameter contract

All **twelve** declared rule paths move from `bypass` to `keyed`, in the same change as the
projection and not before: `temperature`, `max_tokens`, `stop`, `response_format`, `seed`, `n`,
`frequency_penalty`, `presence_penalty`, `logprobs`, `top_logprobs` (ten `direct_rule` calls),
plus `tools` and `tool_choice`, which `function_calling_rules(..., cache_behavior="keyed")` emits
as two separate rules. Each is output-affecting and would have to be keyed for a replay to be
correct.

This is a **caller-visible contract change**: the published parameter contract digests each
rule's `cache_behavior` and `projection_revision`, so every HF model's `contract_id` moves once
and twelve rows of its detail document begin reporting `keyed`.

Two of the twelve — `max_tokens` and `temperature` — are also the fields stored as
`ProfileDefaults`. The ruling-57 body-wins merge happens BEFORE the cache lookup, so the key
describes the EFFECTIVE request: two callers whose stored defaults differ key differently even
when their wire bodies are identical. That is what makes promoting these two safe.

### Accepted consequence — an invalid parameter COMBINATION is not a wrong hit

`validate_chat_parameter_combination` refuses `top_logprobs` without `logprobs is True` on the
miss path, AFTER the cache read. That is safe only because both fields are keyed (so an invalid
combination keys uniquely) and because a row can exist only for a request that dispatched
successfully. INVARIANT this rests on: the combination predicate stays a pure function of KEYED
body fields. `auth_mode` is structurally absent from the key, so a future combination rule that
consulted the auth mode, the resolved model, or any deployment state would reintroduce exactly
this wrong-hit class and would then require a real bypass.

`top_p` stays observed-but-unruled; a `bypass`→`keyed` promotion cannot enable a parameter no
rule enables. The rules revision `_REVISION` is bumped, and stays separate from
`GLOBAL_CACHE_ADAPTER_REVISION`: one versions what a caller may say and where it lands, the
other versions what the boundary adds on its own.

HF's `available_auth_modes()` is exactly `("api_key",)` and `_AUTH` already matches it, so a
keyed rule covers every available mode with no change.

## 7. Caller-influenceable transport

An `extra_headers` value that a caller can steer is output-affecting and must be projected or
bypassed; one that only the gateway sets is transport and is excluded. The parameter contract is
fail-closed — a field reaches the provider body only through a rule, and no rule declares
`extra_headers` — so it is gateway-set only. The plan verifies this claim in code before relying
on it, and bypasses if the trace shows otherwise.

## 8. Cache-hit metadata

`HuggingFaceProviderPlugin` gains `cache_reference_from_cached_response` returning `None`.

This is not decoration. `core/../plugins/taxonomy/session.py::attach_hit_metadata` reaches the
hook through `getattr` inside a `try`, so a provider that simply does not implement it logs
`cache-reference mapper failed provider=huggingface` on **every** hit — reporting a failure that
never happened. HF contributes no usage-accounting strategy at all (unlike Anthropic and
OpenRouter, each of which owns a `usage_accounting.py`), so there is nothing truthful to attach,
and an explicit `None` is the honest answer. Building an HF accounting strategy is out of scope.

## 9. Accepted consequence — gated-repo licensing under cross-account replay

Flagged for owner sign-off; it is not an implementation detail.

Exact replay is cross-account by design, and a hit re-checks nothing — no availability check, no
access check. HF adds a dimension no other projecting provider has: most seeds in
`_default_model_slugs()` are **gated repositories**, whose access requires per-HF-account
acceptance of the model's license. So a row filled by an account that accepted a license can be
served to an account that never did.

This is the same accepted-consequence class OME-884 recorded for direct OpenAI, but qualitatively
different: OpenAI's concerns access control inside one vendor relationship, whereas this touches a
third party's licensing terms.

It is accepted here because it follows from the approved exact-replay semantics rather than from
anything this unit designs — the cache changes who may READ a stored answer, never what goes on
the wire. If the owner declines it, the remedy is a catalog-level seeding or gating decision, not
a projection change, so it does not reshape the work.

## 10. Non-goals and invariants preserved

Out of scope: streaming, `top_p` promotion, the sibling OME-787 projections, `X-HF-Bill-To`, an
HF usage-accounting strategy, runtime model discovery, gateway-owned aliases, cache retention,
cost estimation, schema or migration change, dependency change.

Preserved: the closed bypass-reason vocabulary (`PROJECTION_BYPASS_REASON` only — no new reason
is minted); the cache-key schema; route ordering in `routes/chat.py` and `chat_cache_stage.py`;
request-cache persistence; every existing HF dispatch, discovery, validation and parameter
contract; and OpenRouter, Anthropic and Codex behaviour. No core port signature changes — a
provider adding only a projection needs none.
