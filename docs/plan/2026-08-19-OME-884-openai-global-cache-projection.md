# OME-884 implementation plan: direct OpenAI global-cache projection

## Status

Approved implementation contract. IMPLEMENTED — see the work ledger for the outcome. This file
is retained verbatim as the contract that was approved, so the pre-implementation wording below
describes intent at approval time rather than current state; where the two differ, the ledger
and the spec are authoritative.

`plan_review.md` and `plan_review_v2.md` reviewed superseded drafts. They remain historical evidence,
not the active implementation contract.

PR #630 squash-merged OME-864 as `bab02e3e`. On 2026-08-19 the OME-884 branch was rebased from the
old OME-864 tip onto fresh `origin/main` at `9e051879`; the aggregate OME-864 patch-id matched the
squash commit, and OME-884 had zero commits to replay. `HEAD` and `origin/main` were identical after
the operation.

The owner explicitly authorized implementation in the current shared checkout and directed that no
worktree be used. Existing unrelated staged, unstaged, untracked, and stash state must remain
untouched. All implementation units land as one PR; no intermediate unit is deployed.

## Owner-approved MVP semantics

- Every syntactically valid `openai/*` model is directly dispatchable and globally cacheable.
- `OpenAIPluginSettings.default_models` is the bootstrap catalog published by `/v1/models`, not a
  dispatch or cache allowlist.
- A locally configured or directly addressed custom model follows the same miss/store/hit path as a
  default model.
- Removing a model from `default_models` only removes it from the published catalog. Direct calls and
  existing exact replay remain available.
- OpenAI validates model existence and caller access on a cache miss. A hit intentionally performs no
  current provider-availability or caller-access check.
- This accepted exact-replay behavior includes the case where a previously successful model later
  disappears upstream or becomes unavailable to the current caller.
- Future runtime model discovery updates the published catalog only. It is not implemented by OME-884
  and is not a prerequisite for dispatch or cache eligibility.
- Provider-published model aliases are ordinary model IDs. Ambient process-global
  `litellm.model_alias_map` redirects are not a supported alias feature and fail closed for the
  requested model.

## Phase 0: authorize and frame

Before the first test or production edit:

1. Confirm OME-884 remains In Progress under OME-787 and that merged OME-864 is no longer a blocker.
2. Create the required `docs/tasks/` mirror and approved `docs/spec/` artifact.
3. Promote the approved plan to `docs/plan/`; keep scratch drafts outside the committed change.
4. Create `docs/work/2026-08-19-OME-884-openai-global-cache-projection.md` from
   `docs/work/TEMPLATE.md` before the first test.
5. Work in the current `OME-884-openai-global-cache-projection` checkout as explicitly authorized.
   Do not switch branches or disturb unrelated worktree/index/stash state.
6. Confirm the exact installed LiteLLM version and source paths used by the design.
7. Run the complete AIGateway gate as a baseline and record it in the ledger.
8. Confirm owner approval for the seven prior OME-864 assertions whose product contract necessarily
   changes, and record the append-only exception procedure below.

## Existing contract

- OME-864 provides direct `openai/*` API-key access for non-streaming Chat Completions.
- OME-864 currently restricts dispatch to `default_models`; OME-884 deliberately changes that list to
  catalog-only while retaining strict model-ID syntax validation.
- The provider currently inherits the safe default `CacheBypass` projection.
- `max_tokens` is the only enabled ordinary parameter and currently declares
  `cache_behavior="bypass"`.
- `max_tokens` is also a stored `ProfileDefaults` field. The body-wins defaults merge runs before
  cache planning, so the key sees the effective request.
- Stored `temperature` and `reasoning_effort` defaults remain unsupported and therefore bypass or fail
  existing parameter validation.
- `available_auth_modes()` is exactly `("api_key",)`. A keyed rule must cover every available mode.
- Cache planning runs before auth resolution, `prepare_chat_body`, credential injection, and
  dispatch.
- A hit performs one accepted `aigateway:index` profile-index read and master-key decryption. It must
  not read or decrypt an `aigateway:openai:*` provider credential, resolve an auth mode, inject an API
  key, validate a provider credential, or dispatch.
- A cache key is globally shared and contains no account, profile, credential, organization, or
  project identity.
- Rows may have no expiry and can survive process restarts and deployments. Compatibility changes
  abandon old rows through revisions rather than deleting them.

## Design decisions

### Model identity and catalog semantics

- Reuse one pure predicate for route-valid direct OpenAI IDs in settings validation, preparation,
  projection, and parameter rules.
- A route-valid ID starts with `openai/` and has one bounded ASCII model token accepted by the existing
  validator.
- `register_models()` continues to publish `default_models`; publication does not grant or remove
  dispatch permission.
- `prepare_chat_body()` rejects malformed/non-OpenAI IDs but no longer requires membership in
  `default_models`.
- OpenAI remains authoritative for whether a syntactically valid model exists and whether the selected
  credential may use it.
- Only successful complete responses are stored. A syntactically valid unsupported model misses,
  reaches OpenAI, returns the existing sanitized provider error, and creates no row.
- Fine-tuned/private IDs containing syntax the current validator rejects remain out of scope. If later
  admitted, their cross-account replay semantics require a separate product/security decision.

### Admission and key material remain separate

`global_cache_projection()` describes pure key material. `participates_in_global_cache(model)` checks
deployment-local unsafe runtime state before any cache read or write. The projection never reads a
settings instance, environment variable, credential, identity, clock, random source, filesystem, or
network.

The participation port becomes model-aware only so an ambient LiteLLM redirect can be checked for the
requested model. It does not consult `default_models` or future discovery state.

### Pure provider projection

- Add `plugins/openai_provider/global_cache.py`.
- Define `GLOBAL_CACHE_ADAPTER_REVISION`.
- Return `CacheBypass` for malformed or non-OpenAI IDs.
- Project every syntactically valid `openai/*` ID, whether or not it appears in `default_models`.
- Return `resolved_model`, `provider_adapter_revision`, and JSON-safe `prepared`.
- Keep `prepared` limited to JSON primitives and string-keyed mappings; never place `Omit()` sentinels
  or an SDK client in it.
- Account for the official API base, Chat Completions-only routing, Responses bridge suppression,
  cache disabling, retry controls, and every output-affecting constant added before dispatch.
- Treat `OpenAI-Organization` and `OpenAI-Project` suppression as the explicit condition licensing
  cross-account replay.
- Represent `verify=True`, `trust_env=False`, `follow_redirects=False`, `max_retries=0`, the
  request-local `AsyncOpenAI` transport, and non-JSON sentinels through the adapter revision where
  they cannot be normalized into `prepared`.
- Treat a relevant LiteLLM version or behavior change as a mandatory adapter-revision event because
  persistent rows can survive application deployments.

### Runtime participation and dispatch refusal

Use one shared, total, fail-closed model-free core for unsafe OpenAI runtime state. Reuse it from the
cache participation hook and dispatch guard.

Both paths refuse direct OpenAI when:

- `litellm.OpenAIConfig.get_config()` is non-empty;
- `OPENAI_CUSTOM_HEADERS` is non-empty;
- an existing unsafe LiteLLM callback, fallback, header, proxy-auth, rule, or routing state is active;
- a LiteLLM secret-manager client is configured, because the experimental-handler flag and ambient
  credentials may otherwise be resolved outside the environment.

Use one total helper for the environment branch of
`EXPERIMENTAL_OPENAI_BASE_LLM_HTTP_HANDLER`:

```python
isinstance(value, str) and value.strip().lower() == "true"
```

When it returns true, participation and dispatch refuse direct OpenAI. Test parity with installed
LiteLLM while secret-manager state is cleared, including unset `None`, recognized true/false spellings,
and unrecognized values.

Ambient LiteLLM aliases are deliberately asymmetric:

- participation receives the requested model and bypasses only when that exact model is a key in
  `model_alias_map`;
- dispatch preserves OME-864's existing per-request alias refusal;
- unrelated provider/model aliases do not disable OpenAI cache or dispatch.

Any exception in participation becomes non-participation, never a request failure.

### Model-aware participation port

- Change `ProviderPluginBase.participates_in_global_cache()` to accept the raw requested model.
- Pass `body.get("model")` from `build_global_cache_plan()` without reordering the existing gates.
- The default implementation ignores the model and returns true.
- OpenRouter accepts and ignores the model while preserving its current `settings.enabled` behavior.
- OpenAI uses the model only for exact ambient-alias detection.
- Do not pass the request body, settings, account, auth mode, or credentials through this port.

### Parameter promotion

- Return a keyed `max_tokens` rule for every syntactically valid `openai/*` model.
- Promote `max_tokens` only in the same increment as the real projection.
- Bump its projection revision.
- The key includes both model and effective `max_tokens`, so different models or values cannot
  collide even when LiteLLM maps the field differently.
- Pin GPT-4/4o `max_tokens` and GPT-5/o-series `max_completion_tokens` behavior at the final HTTP wire
  for all fourteen default models.
- Name the exact installed LiteLLM pin and the wire-mapping test as adapter-revision inputs. A future
  LiteLLM change must bump the adapter revision before persistent rows can be reused.
- Run equal/different-key proofs through `build_global_cache_plan()` so provider auth modes, rules,
  participation, and projection are exercised together.

### Cache-hit accounting metadata

Add `OpenAIProviderPlugin.cache_reference_from_cached_response()` returning `None`. Direct OpenAI
certifies no historical accounting evidence for a replayed row. A hit renders cache status without a
false mapper warning; accounting remains unsupported on hits and misses.

## Existing tests that necessarily change

The following committed OME-864 assertions describe contracts intentionally changed by this MVP. Each
must become a positive replacement, never be deleted or weakened:

- `test_openai_provider.py`: canonical `max_tokens` changes from `bypass` to `keyed`.
- `test_openai_provider.py`: the provider changes from inherited `CacheBypass` to a real projection.
- `test_openai_gateway_acceptance.py`: the published parameter contract changes to `keyed`.
- `test_openai_dispatch.py`: a syntactically valid unlisted model is forwarded rather than rejected as
  locally unregistered; malformed IDs remain locally rejected.
- `test_openai_gateway_acceptance.py`: a syntactically valid unlisted model no longer follows the
  pre-credential `invalid_model` case; replace it with malformed-ID and provider-rejection coverage.
- `test_openai_provider.py`: `validation_model` no longer has to appear in the bootstrap catalog;
  syntax validation remains mandatory.
- `test_openai_api_key_validation.py`: a route-valid validation model outside `default_models` is no
  longer locally misconfigured and is probed normally.

Run the gate normally, confirm the append-only failure names only these approved files/assertions,
then rerun with `--skip-append-only` and record both outputs and the owner decision in the ledger.
Every other prior test remains unchanged and green.

## Test-first implementation sequence

### Unit 1: pure projection and model-ID contract

Add RED tests proving:

- deterministic output and no body mutation;
- malformed/non-OpenAI model bypass;
- default and syntactically valid unlisted custom models project identically except for keyed model;
- a route-valid `validation_model` remains usable when omitted from `default_models`;
- complete normalized provider-added state;
- JSON-safe `prepared` and successful key construction;
- adapter-revision isolation;
- key-level distinction for present versus absent top-level `system`.

Implement the shared model-ID predicate and pure projection only. Do not add provider hooks yet.

### Unit 2: participation, dispatch refusal, and hit safety

Add RED tests proving:

- the model-aware participation port receives the raw requested model;
- an ambient alias bypasses/refuses only its exact requested model while an unrelated model still
  participates and dispatches;
- non-empty OpenAIConfig, experimental-handler true, secret-manager state, and existing unsafe globals
  disable participation and dispatch;
- the flag helper is total for `None` and matches installed LiteLLM environment semantics;
- a fill-then-enable-ambient-state tripwire preserves one row but refuses to replay it;
- a hit performs no OpenAI provider-credential work, auth resolution, validation, key injection, or
  dispatch; the profile-index read remains allowed;
- caller opt-out bypasses;
- a hit emits no cache-reference warning and reports accounting-not-supported.

Standing invariants, green on arrival rather than RED:

- the projection reads no settings, environment, clock, randomness, filesystem, network, credential,
  or identity;
- safe runtime state participates.

Implement the bounded core signature change, OpenRouter signature preservation, OpenAI hooks, shared
runtime predicate, dispatch refusal, and no-op cache-reference mapper together. This is the first unit
that enables OpenAI cache reads and writes; its hit-safety proofs land in the same increment.

### Unit 3: keyed parameter contract

Add RED tests proving:

- default and unlisted route-valid OpenAI models publish keyed `max_tokens` rules;
- equal effective values produce equal plans and keys;
- different models or values produce different keys;
- the rule covers every available auth mode.

Standing invariant: the generic keyed-rule-to-projection conformance suite remains green for every
registered model.

Promote the rule and revision only after the real projection and participation hooks exist.

### Unit 4: catalog-independent route behavior

Use a cache-enabled fixture whose environment is installed before app construction. Every cache test
positively proves the switch is active.

Add route-level tests proving:

- a default model produces `miss -> hit`, one dispatch, and one row;
- a syntactically valid unlisted custom model also produces `miss -> hit`;
- different default/custom models and explicit/defaulted `max_tokens` values do not collide;
- removing a model from `default_models` removes it from `/v1/models` but does not prevent a direct
  call or replay of its successful row;
- a malformed model performs no cache read/write and follows the local invalid-model path;
- a syntactically valid unsupported model misses, reaches a mocked provider rejection, and stores no
  response;
- profile-default `max_tokens` differences isolate, while explicit/default equivalent values share;
- different stored `system_prompt` values produce different effective messages and keys;
- exact effective requests replay across accounts without identity in the key;
- caller opt-out bypasses;
- Codex and OpenRouter behavior remains unchanged.

Split dispatch-boundary proof into three observable layers:

- capture `litellm.acompletion` kwargs for gateway-owned LiteLLM controls;
- inspect `AsyncOpenAI` and httpx construction for client, retry, TLS, proxy, and environment behavior;
- use `MockTransport` for final HTTP URL, headers, payload, and all-fourteen token-field mapping.

Do not call the `litellm.acompletion` boundary the final HTTP wire. No single observation contains
every revision-owned control.

## Planned files

Production:

- `apps/aigateway/src/aigateway/core/plugin_base/_provider.py` - model-aware participation port.
- `apps/aigateway/src/aigateway/core/request_cache/global_plan.py` - pass the raw requested model.
- `apps/aigateway/src/aigateway/plugins/openrouter_provider/plugin.py` - signature-only preservation.
- `apps/aigateway/src/aigateway/plugins/openai_provider/global_cache.py` - pure projection, at most 450
  physical lines.
- `apps/aigateway/src/aigateway/plugins/openai_provider/settings.py` - shared pure model-ID predicate;
  default catalog remains unchanged and no longer constrains `validation_model` membership.
- `apps/aigateway/src/aigateway/plugins/openai_provider/api_key_validation.py` - validate the readiness
  model by syntax rather than catalog membership.
- `apps/aigateway/src/aigateway/plugins/openai_provider/plugin.py` - catalog-independent preparation,
  projection/participation hooks, shared runtime guard, and no-op cache-reference hook.
- `apps/aigateway/src/aigateway/plugins/openai_provider/parameters.py` - keyed rule and revision.

Tests:

- `apps/aigateway/tests/unit/test_global_cache_plan.py` - model-aware port contract.
- `apps/aigateway/tests/unit/openrouter/test_openrouter_routing_policy_routes.py` - unchanged behavior
  through the new signature.
- `apps/aigateway/tests/unit/openrouter/test_openrouter_global_cache_projection.py` - participation
  signature adaptation with unchanged enabled/disabled behavior.
- `apps/aigateway/tests/unit/openai/test_openai_global_cache_projection.py` - new projection/key tests.
- `apps/aigateway/tests/unit/openai/test_openai_provider.py` - positive cache contract updates.
- `apps/aigateway/tests/unit/openai/test_openai_dispatch.py` - pass-through, guards, constructor, and
  final-wire proofs.
- `apps/aigateway/tests/unit/openai/test_openai_gateway_acceptance.py` - cache-enabled route, custom
  model, catalog independence, profile defaults, hit isolation, and metadata tests.
- `apps/aigateway/tests/unit/openai/test_openai_api_key_validation.py` - readiness model independence
  from the published catalog.
- Existing generic cache conformance, purity, key, plan, and route tests - exercised unchanged except
  for the participation signature adaptation.

Durable artifacts:

- `docs/tasks/2026-08-19-OME-884-openai-global-cache-projection.md`.
- `docs/spec/2026-08-19-OME-884-openai-global-cache-projection.md`.
- `docs/plan/2026-08-19-OME-884-openai-global-cache-projection.md`.
- `docs/work/2026-08-19-OME-884-openai-global-cache-projection.md`.

The following must not change without returning to owner review:

- cache key schema or caller-visible reason vocabulary;
- `apps/aigateway/src/aigateway/routes/chat.py` and `chat_cache_stage.py`;
- request-cache persistence/store/models or migrations;
- dependency manifests or lockfiles;
- Codex, Anthropic, and OpenRouter behavior beyond the required participation signature adaptation.

## Stop conditions

Stop implementation and return to owner review rather than broadening scope if:

- pure projection requires credentials, identity, settings, provider I/O, or mutable runtime state;
- safe behavior requires route-order changes, cache persistence changes, or provider availability
  checks on hits;
- a private/fine-tuned account-specific model syntax must be admitted;
- a runtime global can change the final call after participation and dispatch refusal checks;
- the change requires runtime discovery, gateway-owned aliases, schema/migrations, dependencies,
  Responses API, streaming, tools, new request parameters, prompt caching, accounting expansion,
  retention, or cost estimation;
- a required prior-test change extends beyond the seven named contract updates and mechanical
  participation-signature adaptations.

## Verification

From the repository root, run the normal baseline before edits. Before protected prior tests change,
use the same command for complete per-unit gates:

```sh
uv run .claude/scripts/run_gates.py aigateway
```

Run focused tests from `apps/aigateway`:

```sh
uv run pytest tests/unit/openai/test_openai_global_cache_projection.py -q
uv run pytest tests/unit/openai/test_openai_provider.py -q
uv run pytest tests/unit/openai/test_openai_dispatch.py -q
uv run pytest tests/unit/openai/test_openai_gateway_acceptance.py -q
uv run pytest tests/unit/openai/test_openai_api_key_validation.py -q
uv run pytest tests/unit/test_global_cache_registry_conformance.py \
  tests/unit/test_global_cache_projection_purity.py \
  tests/unit/test_global_cache_plan.py \
  tests/unit/test_chat_global_cache_route.py \
  tests/unit/openrouter/test_openrouter_routing_policy_routes.py \
  tests/unit/openrouter/test_openrouter_global_cache_projection.py -q
```

Once protected prior tests change, run the normal command once and record its expected append-only
policy failure. It stops before the actual gates. Run complete per-unit and final gates with:

```sh
uv run .claude/scripts/run_gates.py aigateway --skip-append-only
```

Review tracked OME-884 worktree changes against current main without including unrelated root state:

```sh
git diff --stat origin/main -- apps/aigateway
git diff --check origin/main -- apps/aigateway
git diff --name-only origin/main -- apps/aigateway
wc -l apps/aigateway/src/aigateway/plugins/openai_provider/global_cache.py
```

`git diff` does not include untracked files. Before reporting completion, read every intended new
source/test/durable-artifact file directly and reconcile it with `git status --short`. After a future
owner-authorized commit, `git log --oneline origin/main..HEAD` and `git diff --stat
origin/main...HEAD` must contain only OME-884 work.

Fill the ledger Outcome with actual files, gates, deviations, and commit status before owner handoff.

## Test matrix

| Acceptance claim | Proof |
|---|---|
| Default model exact replay | Route miss, stored write, hit, one dispatch, one row |
| Custom model exact replay | Unlisted route-valid model follows the same miss/hit path |
| Catalog is not an allowlist | Removing a seed hides listing only; direct replay still works |
| Request differences isolate | Model, messages, explicit/defaulted `max_tokens` cases |
| Projection is pure and JSON-safe | Purity sweeps plus successful key construction |
| Runtime globals cannot poison a row | Participation and dispatch refusal tests |
| Ambient redirect cannot replay | Exact-model fill-then-alias tripwire with row preserved |
| Hit avoids provider identity work | Guarded provider read/decrypt/validation/injection/dispatch |
| Unsupported misses do not store | Mocked OpenAI rejection and zero rows |
| Cross-account replay is identity-free | Two accounts, one request, one row, no identity key fields |
| LiteLLM boundary matches projection | Captured gateway-owned acompletion kwargs |
| Client construction is pinned | AsyncOpenAI/httpx retry, TLS, proxy, environment assertions |
| Token-field mapping is pinned | Fourteen default models asserted at final HTTP wire |
| Hit metadata is truthful and quiet | No mapper warning; accounting-not-supported metadata |
| Other providers do not regress | Focused OpenRouter/Codex tests plus complete gate |

## Definition of done

- Linear, task, spec, plan, and work artifacts agree on the owner-approved MVP semantics.
- Implementation ran in the owner-approved current checkout without disturbing unrelated state.
- Every route-valid `openai/*` model, including unlisted custom IDs, can dispatch and cache.
- `default_models` affects publication only, not direct dispatch or cache eligibility.
- Pure projection is total, non-mutating, JSON-safe, identity-free, and credential-free.
- OpenAIConfig, experimental transport, secret-manager state, and existing unsafe globals fail closed
  in participation and dispatch.
- Ambient aliases affect only the exact requested model; unrelated aliases do not disable OpenAI.
- `max_tokens` is keyed for every route-valid model and different models/values isolate.
- All fourteen default models pin LiteLLM token-field mapping at final HTTP wire. Cycle 2
  strengthened this: each of the fourteen now has an EXPLICIT committed expected spelling
  (`_EXPECTED_TOKEN_FIELD`), observed against installed LiteLLM 1.97.0 and asserted with the
  other spelling's absence. Before that, only four were pinned by name and the remaining ten
  were covered by a spelling-agnostic "exactly one token field exists" assertion, which a
  single-model move between spellings would have passed.
- Eligible identical requests produce `miss -> hit`; unsupported misses never store.
- Hits perform no OpenAI provider-credential work, dispatch, provider availability check, or caller
  access check and emit truthful metadata.
- No schema, migration, dependency, route-order, runtime-discovery, alias-feature, retention, or
  accounting-expansion change exists.
- The append-only exception contains only the seven named prior assertions and mechanical signature
  adaptations.
- Focused tests and the complete AIGateway gate pass.
- Path-scoped tracked diffs plus directly read untracked intended files contain only OME-884 work;
  new production files are at most 450 lines; the ledger records the actual uncommitted result.
